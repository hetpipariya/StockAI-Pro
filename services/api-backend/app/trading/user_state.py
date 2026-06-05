"""
Per-user trading state management.

Each user gets an isolated runtime state cached in-memory and persisted to DB.
This avoids shared global trading context while keeping request-time lookups fast.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
import contextlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import select

from stockai_shared.config import config
from stockai_shared.db.db import AsyncSessionLocal, UserModel, UserTradingStateModel
from stockai_shared.cache.redis_client import get_redis

logger = logging.getLogger(__name__)

_MAX_PERSISTED_ORDERS = 500


def position_to_dict(pos: UserPosition) -> dict:
    return {
        "user_id": pos.user_id,
        "symbol": pos.symbol,
        "direction": pos.direction,
        "quantity": pos.quantity,
        "entry_price": pos.entry_price,
        "stop_loss": pos.stop_loss,
        "target": pos.target,
        "confidence": pos.confidence,
        "mode": pos.mode,
        "reason": pos.reason,
        "opened_at": pos.opened_at.isoformat(),
        "order_id": pos.order_id,
    }


def dict_to_position(d: dict) -> UserPosition:
    return UserPosition(
        user_id=int(d["user_id"]),
        symbol=d["symbol"],
        direction=d["direction"],
        quantity=int(d["quantity"]),
        entry_price=float(d["entry_price"]),
        stop_loss=float(d["stop_loss"]),
        target=float(d["target"]),
        confidence=int(d["confidence"]),
        mode=d["mode"],
        reason=d.get("reason", ""),
        opened_at=datetime.fromisoformat(d["opened_at"]),
        order_id=d.get("order_id", ""),
    )


def risk_to_dict(risk: UserRiskState) -> dict:
    return {
        "user_id": risk.user_id,
        "starting_capital": risk.starting_capital,
        "current_capital": risk.current_capital,
        "daily_pnl": risk.daily_pnl,
        "trades_today": risk.trades_today,
        "open_position_count": risk.open_position_count,
        "halted": risk.halted,
        "last_reset_date": risk.last_reset_date.isoformat(),
        "max_risk_per_trade": risk.max_risk_per_trade,
        "max_trades_per_day": risk.max_trades_per_day,
        "max_concurrent_positions": risk.max_concurrent_positions,
        "daily_loss_limit_pct": risk.daily_loss_limit_pct,
        "min_account_balance": risk.min_account_balance,
    }


def apply_risk_dict(risk: UserRiskState, d: dict) -> None:
    risk.user_id = int(d["user_id"])
    risk.starting_capital = float(d["starting_capital"])
    risk.current_capital = float(d["current_capital"])
    risk.daily_pnl = float(d["daily_pnl"])
    risk.trades_today = int(d["trades_today"])
    risk.open_position_count = int(d["open_position_count"])
    risk.halted = bool(d["halted"])
    risk.last_reset_date = date.fromisoformat(d["last_reset_date"])
    if "max_risk_per_trade" in d:
        risk.max_risk_per_trade = float(d["max_risk_per_trade"])
    if "max_trades_per_day" in d:
        risk.max_trades_per_day = int(d["max_trades_per_day"])
    if "max_concurrent_positions" in d:
        risk.max_concurrent_positions = int(d["max_concurrent_positions"])
    if "daily_loss_limit_pct" in d:
        risk.daily_loss_limit_pct = float(d["daily_loss_limit_pct"])
    if "min_account_balance" in d:
        risk.min_account_balance = float(d["min_account_balance"])


@contextlib.asynccontextmanager
async def redis_lock(user_id: int, timeout_ms: int = 10000):
    lock_key = f"stockai:lock:user_state:{user_id}"
    lock_value = str(uuid.uuid4())
    redis_client = await get_redis()
    acquired = False
    
    if redis_client:
        for _ in range(50):
            try:
                res = await redis_client.set(lock_key, lock_value, nx=True, px=timeout_ms)
                if res:
                    acquired = True
                    break
            except Exception as e:
                logger.debug(f"[Lock] Redis lock acquisition error: {e}")
            await asyncio.sleep(0.1)
            
    if not acquired:
        logger.warning("[Lock] Failed to acquire Redis lock for user %s, falling back to local lock", user_id)
        
    try:
        yield acquired
    finally:
        if acquired and redis_client:
            try:
                val = await redis_client.get(lock_key)
                if val == lock_value:
                    await redis_client.delete(lock_key)
            except Exception as e:
                logger.warning("[Lock] Failed to release Redis lock for user %s: %s", user_id, e)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    return parsed if parsed == parsed else default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _normalize_mode(value: Any, fallback: str = "PAPER") -> str:
    mode = str(value or fallback).strip().upper()
    return mode if mode in {"PAPER", "LIVE"} else fallback


def _parse_opened_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except Exception:
            pass
    return datetime.utcnow()


@dataclass
class UserPosition:
    """A single open position for a specific user."""

    user_id: int
    symbol: str
    direction: str  # "BUY" or "SELL"
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    confidence: int
    mode: str  # "paper" or "live"
    reason: str = ""
    opened_at: datetime = field(default_factory=datetime.utcnow)
    order_id: str = ""


@dataclass
class UserRiskState:
    """
    Daily risk state per user.
    Tracks capital, drawdown, and trading limits.
    """

    user_id: int
    starting_capital: float
    current_capital: float
    daily_pnl: float = 0.0
    trades_today: int = 0
    open_position_count: int = 0
    halted: bool = False
    last_reset_date: date = field(default_factory=date.today)

    # Configurable limits (pulled from config defaults)
    max_risk_per_trade: float = field(
        default_factory=lambda: config.MAX_RISK_PER_TRADE_PCT
    )
    max_trades_per_day: int = field(default_factory=lambda: config.MAX_TRADES_PER_DAY)
    max_concurrent_positions: int = field(
        default_factory=lambda: config.MAX_CONCURRENT_POSITIONS
    )
    daily_loss_limit_pct: float = field(
        default_factory=lambda: config.DAILY_LOSS_LIMIT_PCT
    )
    min_account_balance: float = field(
        default_factory=lambda: config.MIN_ACCOUNT_BALANCE
    )

    @property
    def daily_pnl_pct(self) -> float:
        if self.starting_capital <= 0:
            return 0.0
        return (self.daily_pnl / self.starting_capital) * 100

    @property
    def max_daily_loss_reached(self) -> bool:
        """Stop trading if daily loss exceeds configured limit of capital."""
        return self.daily_pnl_pct <= -(self.daily_loss_limit_pct * 100)

    def reset_if_new_day(self):
        today = date.today()
        if self.last_reset_date != today:
            self.daily_pnl = 0.0
            self.trades_today = 0
            self.halted = False
            self.last_reset_date = today
            logger.info("[User %s] Daily risk state reset for %s", self.user_id, today)


class UserTradingState:
    """
    Complete isolated trading context for one user.
    Each user gets their own capital, positions, and risk limits.
    """

    def __init__(
        self,
        user_id: int,
        starting_capital: float = 100_000.0,
        mode: str = "PAPER",
    ):
        safe_capital = max(0.0, _to_float(starting_capital, config.STARTING_CAPITAL))
        self.user_id = int(user_id)
        self.mode = _normalize_mode(mode)
        self.positions: dict[str, UserPosition] = {}
        self.trade_journal: list[dict[str, Any]] = []
        self.risk = UserRiskState(
            user_id=self.user_id,
            starting_capital=safe_capital,
            current_capital=safe_capital,
        )
        self._lock = asyncio.Lock()
        logger.info(
            "[TradingState] Created state for user_id=%s capital=Rs%.2f mode=%s",
            self.user_id,
            safe_capital,
            self.mode,
        )

    def can_trade(self) -> tuple[bool, str]:
        """Check if user is allowed to take a new trade."""
        self.risk.reset_if_new_day()

        if self.risk.halted:
            return False, "HALTED: Kill-switch active for your account"

        if not config.TRADING_ENABLED:
            return (
                False,
                "BLOCKED: System-wide kill-switch active (TRADING_ENABLED=false)",
            )

        if self.risk.max_daily_loss_reached:
            return (
                False,
                f"HALTED: Daily loss {self.risk.daily_pnl_pct:.1f}% exceeds limit",
            )

        if self.risk.trades_today >= self.risk.max_trades_per_day:
            return (
                False,
                f"Max trades ({self.risk.max_trades_per_day}) reached for today",
            )

        if len(self.positions) >= self.risk.max_concurrent_positions:
            return (
                False,
                f"Max concurrent positions ({self.risk.max_concurrent_positions}) reached",
            )

        if self.risk.current_capital <= self.risk.min_account_balance:
            self.risk.halted = True
            return (
                False,
                (
                    f"HALTED: Capital {self.risk.current_capital:,.0f} below minimum "
                    f"{self.risk.min_account_balance:,.0f}"
                ),
            )

        return True, "OK"

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "mode": self.mode,
            "positions": {sym: position_to_dict(pos) for sym, pos in self.positions.items()},
            "trade_journal": self.trade_journal,
            "risk": risk_to_dict(self.risk),
        }

    def apply_dict(self, d: dict) -> None:
        self.user_id = int(d["user_id"])
        self.mode = d["mode"]
        self.positions = {sym: dict_to_position(pos_d) for sym, pos_d in d.get("positions", {}).items()}
        self.trade_journal = d.get("trade_journal", [])
        if "risk" in d:
            apply_risk_dict(self.risk, d["risk"])

    async def sync_from_redis(self) -> None:
        redis_client = await get_redis()
        if redis_client:
            try:
                data = await redis_client.get(f"stockai:user_state:{self.user_id}")
                if data:
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    import json
                    parsed = json.loads(data)
                    self.apply_dict(parsed)
            except Exception as e:
                logger.warning(f"[TradingState] Failed to sync from Redis for user {self.user_id}: {e}")

    async def sync_to_redis(self) -> None:
        redis_client = await get_redis()
        if redis_client:
            try:
                import json
                serialized = json.dumps(self.to_dict())
                await redis_client.setex(f"stockai:user_state:{self.user_id}", 86400, serialized)
            except Exception as e:
                logger.warning(f"[TradingState] Failed to sync to Redis for user {self.user_id}: {e}")

    async def open_position(self, pos: UserPosition) -> tuple[bool, str]:
        """
        Open a new position for this user.
        Returns (success, message).
        """
        async with redis_lock(self.user_id):
            await self.sync_from_redis()
            async with self._lock:
                can, reason = self.can_trade()
                if not can:
                    logger.warning("[User %s] Trade blocked: %s", self.user_id, reason)
                    return False, reason

                symbol = str(pos.symbol or "").upper().strip()
                if symbol in self.positions:
                    msg = f"Position already open for {symbol}"
                    logger.warning("[User %s] %s", self.user_id, msg)
                    return False, msg

                pos.symbol = symbol
                pos.mode = str(pos.mode or self.mode).lower()
                self.positions[symbol] = pos
                self.risk.open_position_count = len(self.positions)

                # Log to journal (chronological)
                self.trade_journal.append(
                    {
                        "event": "OPEN",
                        "user_id": self.user_id,
                        "symbol": pos.symbol,
                        "direction": pos.direction,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "stop_loss": pos.stop_loss,
                        "target": pos.target,
                        "confidence": pos.confidence,
                        "mode": pos.mode,
                        "reason": pos.reason,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )

                if len(self.trade_journal) > _MAX_PERSISTED_ORDERS:
                    self.trade_journal = self.trade_journal[-_MAX_PERSISTED_ORDERS:]

                await self.persist()
                await self.sync_to_redis()

                logger.info(
                    "[User %s] Opened %s %s @ Rs%.2f qty=%s SL=Rs%.2f TP=Rs%.2f",
                    self.user_id,
                    pos.direction,
                    pos.symbol,
                    pos.entry_price,
                    pos.quantity,
                    pos.stop_loss,
                    pos.target,
                )
                return True, "Position opened"

    async def close_position(
        self,
        symbol: str,
        exit_price: float,
        reason: str = "",
    ) -> Optional[float]:
        """
        Close a position and calculate PnL.
        Returns realized PnL or None if no position existed.
        """
        async with redis_lock(self.user_id):
            await self.sync_from_redis()
            async with self._lock:
                normalized_symbol = str(symbol or "").upper().strip()
                pos = self.positions.pop(normalized_symbol, None)
                if not pos:
                    return None

                if pos.direction == "BUY":
                    pnl = (exit_price - pos.entry_price) * pos.quantity
                else:
                    pnl = (pos.entry_price - exit_price) * pos.quantity

                self.risk.daily_pnl += pnl
                self.risk.trades_today += 1
                self.risk.current_capital += pnl
                self.risk.open_position_count = len(self.positions)

                # Log to journal (chronological)
                self.trade_journal.append(
                    {
                        "event": "CLOSE",
                        "user_id": self.user_id,
                        "symbol": normalized_symbol,
                        "direction": pos.direction,
                        "quantity": pos.quantity,
                        "entry_price": pos.entry_price,
                        "exit_price": exit_price,
                        "pnl": round(pnl, 2),
                        "reason": reason,
                        "mode": pos.mode,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                    }
                )

                if len(self.trade_journal) > _MAX_PERSISTED_ORDERS:
                    self.trade_journal = self.trade_journal[-_MAX_PERSISTED_ORDERS:]

                await self.persist()
                await self.sync_to_redis()

                logger.info(
                    "[User %s] Closed %s %s @ Rs%.2f pnl=Rs%+.2f reason=%s",
                    self.user_id,
                    pos.direction,
                    normalized_symbol,
                    exit_price,
                    pnl,
                    reason,
                )
                return pnl

    def get_position(self, symbol: str) -> Optional[UserPosition]:
        return self.positions.get(str(symbol or "").upper().strip())

    def has_position(self, symbol: str) -> bool:
        return str(symbol or "").upper().strip() in self.positions

    def get_all_positions(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": p.symbol,
                "direction": p.direction,
                "quantity": p.quantity,
                "entry_price": p.entry_price,
                "stop_loss": p.stop_loss,
                "target": p.target,
                "confidence": p.confidence,
                "mode": p.mode,
                "reason": p.reason,
                "opened_at": p.opened_at.isoformat() + "Z",
                "order_id": p.order_id,
            }
            for p in self.positions.values()
        ]

    async def toggle_kill_switch(self, halt: bool):
        async with redis_lock(self.user_id):
            await self.sync_from_redis()
            self.risk.halted = bool(halt)
            await self.persist()
            await self.sync_to_redis()
            logger.warning(
                "[User %s] Kill-switch %s",
                self.user_id,
                "ACTIVATED" if halt else "DEACTIVATED",
            )

    def get_journal(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return most recent trade journal entries."""
        return self.trade_journal[-max(1, int(limit)) :][::-1]  # Newest first

    def get_summary(self) -> dict[str, Any]:
        self.risk.reset_if_new_day()
        can, reason = self.can_trade()
        return {
            "user_id": self.user_id,
            "mode": self.mode,
            "capital": round(self.risk.current_capital, 2),
            "starting_capital": round(self.risk.starting_capital, 2),
            "daily_pnl": round(self.risk.daily_pnl, 2),
            "daily_pnl_pct": round(self.risk.daily_pnl_pct, 2),
            "trades_today": self.risk.trades_today,
            "max_trades_per_day": self.risk.max_trades_per_day,
            "open_positions": len(self.positions),
            "max_positions": self.risk.max_concurrent_positions,
            "is_halted": self.risk.halted,
            "max_loss_reached": self.risk.max_daily_loss_reached,
            "can_trade": can,
            "can_trade_reason": reason,
            "trading_enabled": config.TRADING_ENABLED,
            "live_confirmed": config.LIVE_CONFIRMED,
        }

    def apply_persisted_payload(
        self,
        balance: float,
        positions_payload: Any,
        orders_payload: Any,
    ) -> None:
        self.risk.current_capital = max(0.0, _to_float(balance, self.risk.current_capital))

        restored_positions: dict[str, UserPosition] = {}
        if isinstance(positions_payload, list):
            for item in positions_payload:
                if not isinstance(item, dict):
                    continue

                symbol = str(item.get("symbol", "")).strip().upper()
                if not symbol:
                    continue

                restored_positions[symbol] = UserPosition(
                    user_id=self.user_id,
                    symbol=symbol,
                    direction=str(item.get("direction", "BUY")).upper(),
                    quantity=max(0, _to_int(item.get("quantity", 0), 0)),
                    entry_price=_to_float(item.get("entry_price", 0.0), 0.0),
                    stop_loss=_to_float(item.get("stop_loss", 0.0), 0.0),
                    target=_to_float(item.get("target", 0.0), 0.0),
                    confidence=max(0, _to_int(item.get("confidence", 0), 0)),
                    mode=str(item.get("mode", self.mode)).lower(),
                    reason=str(item.get("reason", "")),
                    opened_at=_parse_opened_at(item.get("opened_at")),
                    order_id=str(item.get("order_id", "")),
                )

        restored_journal: list[dict[str, Any]] = []
        if isinstance(orders_payload, list):
            for item in orders_payload[-_MAX_PERSISTED_ORDERS:]:
                if isinstance(item, dict):
                    restored_journal.append(dict(item))

        self.positions = restored_positions
        self.trade_journal = restored_journal
        self.risk.open_position_count = len(self.positions)

    async def persist(self) -> None:
        """Flush runtime state to the user_trading_state table."""
        positions_payload = self.get_all_positions()
        orders_payload = self.trade_journal[-_MAX_PERSISTED_ORDERS:]

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserTradingStateModel)
                    .where(UserTradingStateModel.user_id == self.user_id)
                    .limit(1)
                )
                row = result.scalars().first()

                if row is None:
                    row = UserTradingStateModel(
                        user_id=self.user_id,
                        balance=float(self.risk.current_capital),
                        positions=positions_payload,
                        orders=orders_payload,
                        last_updated=datetime.utcnow(),
                    )
                    session.add(row)
                else:
                    row.balance = float(self.risk.current_capital)
                    row.positions = positions_payload
                    row.orders = orders_payload
                    row.last_updated = datetime.utcnow()

                await session.commit()
        except Exception as exc:
            logger.warning(
                "[TradingState] Persist failed for user_id=%s: %s",
                self.user_id,
                exc,
            )


class TradingManager:
    """
    Central registry that maps user_id -> UserTradingState.
    Thread-safe. Provides user isolation for the entire trading subsystem.
    """

    _instance: Optional["TradingManager"] = None

    def __init__(self):
        self._states: dict[int, UserTradingState] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "TradingManager":
        if cls._instance is None:
            cls._instance = TradingManager()
        return cls._instance

    async def _load_or_create_state(
        self,
        user_id: int,
        starting_capital: Optional[float],
        mode: Optional[str],
    ) -> UserTradingState:
        resolved_capital = _to_float(
            starting_capital,
            max(0.0, _to_float(config.STARTING_CAPITAL, 100_000.0)),
        )
        resolved_mode = _normalize_mode(mode, config.TRADING_MODE)

        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(
                        UserModel.starting_capital,
                        UserModel.trading_mode,
                        UserTradingStateModel,
                    )
                    .outerjoin(
                        UserTradingStateModel,
                        UserTradingStateModel.user_id == UserModel.id,
                    )
                    .where(UserModel.id == user_id)
                    .limit(1)
                )
                row = result.first()

                if row is not None:
                    user_capital, user_mode, persisted_state = row

                    if starting_capital is None:
                        resolved_capital = _to_float(user_capital, resolved_capital)
                    if mode is None:
                        resolved_mode = _normalize_mode(user_mode, resolved_mode)

                    state = UserTradingState(
                        user_id=user_id,
                        starting_capital=resolved_capital,
                        mode=resolved_mode,
                    )

                    if persisted_state is not None:
                        state.apply_persisted_payload(
                            balance=_to_float(persisted_state.balance, resolved_capital),
                            positions_payload=persisted_state.positions,
                            orders_payload=persisted_state.orders,
                        )
                    else:
                        # Create baseline persisted row eagerly for reconnect-safe WS snapshots.
                        session.add(
                            UserTradingStateModel(
                                user_id=user_id,
                                balance=float(state.risk.current_capital),
                                positions=state.get_all_positions(),
                                orders=[],
                                last_updated=datetime.utcnow(),
                            )
                        )
                        await session.commit()

                    return state
        except Exception as exc:
            logger.warning(
                "[TradingManager] DB state bootstrap failed for user_id=%s: %s",
                user_id,
                exc,
            )

        # Fallback: keep trading path available even if DB bootstrap fails.
        return UserTradingState(
            user_id=user_id,
            starting_capital=resolved_capital,
            mode=resolved_mode,
        )

    async def get_state(
        self,
        user_id: int,
        starting_capital: Optional[float] = None,
        mode: Optional[str] = None,
    ) -> UserTradingState:
        """
        Get or create isolated trading state for a user.
        The state is cached in-memory and persisted in DB.
        """
        key = int(user_id)
        redis_client = await get_redis()
        if redis_client:
            try:
                await redis_client.sadd("stockai:active_users", str(key))
            except Exception as e:
                logger.warning("[TradingManager] Failed to add active user to Redis: %s", e)

        async with self._lock:
            if key not in self._states:
                state = await self._load_or_create_state(
                    user_id=key,
                    starting_capital=starting_capital,
                    mode=mode,
                )
                self._states[key] = state
                await state.sync_from_redis()
            else:
                await self._states[key].sync_from_redis()
                if mode is not None:
                    self._states[key].mode = _normalize_mode(mode, self._states[key].mode)
            return self._states[key]

    async def remove_state(self, user_id: int):
        """Drop in-memory state cache for a user (persistent DB state remains)."""
        async with self._lock:
            state = self._states.pop(int(user_id), None)
            redis_client = await get_redis()
            if redis_client:
                try:
                    await redis_client.srem("stockai:active_users", str(user_id))
                    await redis_client.delete(f"stockai:user_state:{user_id}")
                except Exception as e:
                    logger.warning("[TradingManager] Failed to remove active user from Redis: %s", e)
            if state:
                logger.info(
                    "[TradingManager] Removed in-memory state for user_id=%s (had %s open positions)",
                    user_id,
                    len(state.positions),
                )

    async def get_active_user_count(self) -> int:
        redis_client = await get_redis()
        if redis_client:
            try:
                return await redis_client.scard("stockai:active_users")
            except Exception as e:
                logger.warning("[TradingManager] Failed to get active user count from Redis: %s", e)
        return len(self._states)

    async def get_all_summaries(self) -> list[dict[str, Any]]:
        redis_client = await get_redis()
        if redis_client:
            try:
                user_ids = await redis_client.smembers("stockai:active_users")
                summaries = []
                for uid_str in user_ids:
                    try:
                        uid = int(uid_str)
                        state = await self.get_state(uid)
                        summaries.append(state.get_summary())
                    except Exception:
                        pass
                return summaries
            except Exception as e:
                logger.warning("[TradingManager] Failed to get all summaries from Redis: %s", e)
        return [state.get_summary() for state in self._states.values()]


# Module-level singleton accessor
trading_manager = TradingManager.get_instance()
