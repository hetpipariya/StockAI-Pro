"""
Order Router — executes trades in PAPER or LIVE mode.
PAPER mode logs trades to SQLite without touching real money.
LIVE mode routes orders through SmartAPI (Angel One).
All state transitions are logged via the trade_logger audit trail.
"""
from __future__ import annotations

import logging
import uuid
import time
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from app import config
from app.services.db import get_sync_db_session, OrderModel, PositionModel, OrderStateLog
from app.trading.trade_logger import log_trade

logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    order_id: str
    symbol: str
    direction: str
    quantity: int
    price: float
    stop_loss: float
    target: float
    status: str       # "FILLED", "REJECTED", "PENDING_CONFIRMATION", "FAILED", "PARTIAL"
    mode: str          # "PAPER" or "LIVE"
    timestamp: str
    error: Optional[str] = None
    reason: Optional[str] = None
    confidence: int = 0


class OrderRouter:
    """
    Routes trade signals to either Paper or Live execution.
    Maintains trade state and positions centrally in the database.
    """

    def __init__(self, mode: str = "PAPER"):
        """mode: 'PAPER' or 'LIVE'"""
        self.mode = mode.upper()
        
        # Override mode if safety flags prevent LIVE trading
        if self.mode == "LIVE":
            if not config.TRADING_ENABLED:
                logger.warning("[SAFETY] TRADING_ENABLED is False or missing. Forcing PAPER mode.")
                self.mode = "PAPER"
            elif config.TRADING_MODE != "LIVE":
                logger.warning(f"[SAFETY] TRADING_MODE env is {config.TRADING_MODE}, not LIVE. Forcing PAPER.")
                self.mode = "PAPER"
            elif not config.LIVE_CONFIRMED:
                logger.warning("[SAFETY] LIVE_CONFIRMED is False. LIVE mode requires explicit confirmation. Forcing PAPER.")
                self.mode = "PAPER"

        logger.info(f"[ORDER] Router initialized in {self.mode} mode")

    def _log_state(self, session, order_id: str, state: str):
        """Append to order lifecycle state machine log"""
        log = OrderStateLog(order_id=order_id, state=state)
        session.add(log)
        logger.info(f"[ORDER-STATE] {order_id} -> {state}")

    def place_order(
        self,
        symbol: str,
        direction: str,
        quantity: int,
        price: float,
        stop_loss: float,
        target: float,
        reason: str = "",
        confidence: int = 0
    ) -> OrderResult:
        """
        Stage 1: A trade signal is validated. 
        Create order in PENDING_CONFIRMATION state in the database.
        Idempotency: prevent exact duplicates in the last 15 minutes.
        """
        # Kill-switch check at order placement time
        if not config.TRADING_ENABLED:
            logger.warning(f"[SAFETY] Kill-switch active — blocking order for {symbol}")
            log_trade(
                "REJECTED", order_id="N/A", symbol=symbol, direction=direction,
                quantity=quantity, price=price, stop_loss=stop_loss, target=target,
                confidence=confidence, reason=reason, mode=self.mode,
                status="REJECTED", error="Kill-switch active (TRADING_ENABLED=false)",
            )
            return OrderResult(
                order_id="BLOCKED", symbol=symbol, direction=direction,
                quantity=quantity, price=price, stop_loss=stop_loss, target=target,
                status="REJECTED", mode=self.mode,
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                error="Kill-switch active (TRADING_ENABLED=false)",
            )

        db_gen = get_sync_db_session()
        session = next(db_gen)

        try:
            # Idempotency Check
            recent_duplicate = session.query(OrderModel).filter(
                OrderModel.symbol == symbol,
                OrderModel.transaction_type == direction,
                OrderModel.status.in_(["PENDING_CONFIRMATION", "CONFIRMED", "PENDING_EXECUTION", "FILLED"])
            ).order_by(OrderModel.timestamp.desc()).first()

            if recent_duplicate:
                time_diff = (datetime.utcnow() - recent_duplicate.timestamp).total_seconds()
                if time_diff < 900: # 15 minutes
                    logger.warning(f"[ORDER] Idempotency block: Exact {direction} order for {symbol} placed {time_diff:.0f}s ago. Skipping.")
                    log_trade(
                        "REJECTED", order_id=recent_duplicate.order_id, symbol=symbol,
                        direction=direction, quantity=quantity, price=price,
                        mode=self.mode, status="REJECTED",
                        error="Duplicate order block (Idempotency)",
                    )
                    return OrderResult(
                        order_id=recent_duplicate.order_id, symbol=symbol, direction=direction,
                        quantity=quantity, price=price, stop_loss=stop_loss, target=target,
                        status="REJECTED", mode=self.mode, timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                        error="Duplicate order block (Idempotency)"
                    )

            order_id = f"{self.mode}-{uuid.uuid4().hex[:8].upper()}"
            
            new_order = OrderModel(
                order_id=order_id,
                symbol=symbol,
                transaction_type=direction,
                quantity=quantity,
                price=price,
                stop_loss=stop_loss,
                target=target,
                status="PENDING_CONFIRMATION",
                mode=self.mode,
                reason=reason,
                confidence=confidence
            )
            session.add(new_order)
            self._log_state(session, order_id, "PENDING_CONFIRMATION")
            session.commit()

            logger.info(f"[{self.mode}] Staged {direction} {quantity}x {symbol} @ ₹{price:.2f} | ID={order_id}. Awaiting Confirmation.")
            
            # Audit log
            log_trade(
                "PLACED", order_id=order_id, symbol=symbol, direction=direction,
                quantity=quantity, price=price, stop_loss=stop_loss, target=target,
                confidence=confidence, reason=reason, mode=self.mode,
                status="PENDING_CONFIRMATION",
            )

            return OrderResult(
                order_id=order_id, symbol=symbol, direction=direction,
                quantity=quantity, price=price, stop_loss=stop_loss, target=target,
                status="PENDING_CONFIRMATION", mode=self.mode,
                timestamp=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                reason=reason, confidence=confidence
            )

        finally:
            session.close()

    def confirm_and_execute(self, order_id: str) -> Optional[OrderResult]:
        """
        Stage 2: External API triggers execution of a PENDING_CONFIRMATION order.
        Moves state machine and routes to correct executor.
        """
        db_gen = get_sync_db_session()
        session = next(db_gen)

        try:
            order = session.query(OrderModel).filter_by(order_id=order_id).first()
            if not order:
                logger.error(f"[ORDER] Cannot confirm missing order {order_id}")
                return None
            
            if order.status != "PENDING_CONFIRMATION":
                logger.error(f"[ORDER] Order {order_id} is in state {order.status}, cannot confirm.")
                return None

            # Validate Mode matches safety rules dynamically
            execute_mode = order.mode
            if execute_mode == "LIVE" and (not config.TRADING_ENABLED or config.TRADING_MODE != "LIVE"):
                logger.error(f"[SAFETY] Execution blocked for LIVE order {order_id} due to env change.")
                order.status = "REJECTED"
                order.error = "Safety Block triggered during execution"
                self._log_state(session, order_id, "REJECTED")
                session.commit()
                log_trade(
                    "REJECTED", order_id=order_id, symbol=order.symbol,
                    direction=order.transaction_type, quantity=order.quantity,
                    price=order.price, mode=execute_mode, status="REJECTED",
                    error="Safety Block triggered during execution",
                )
                return None

            order.status = "CONFIRMED"
            self._log_state(session, order_id, "CONFIRMED")
            session.commit()

            log_trade(
                "CONFIRMED", order_id=order_id, symbol=order.symbol,
                direction=order.transaction_type, quantity=order.quantity,
                price=order.price, mode=execute_mode, status="CONFIRMED",
            )

            logger.info(f"[{execute_mode}] Executing confirmed order {order_id}")
            
            if execute_mode == "PAPER":
                result = self._execute_paper(session, order)
            else:
                result = self._execute_live(session, order)

            return result

        finally:
            session.close()

    def _execute_paper(self, session, order: OrderModel) -> OrderResult:
        """Instantly fill the PAPER order and create a Position."""
        order.status = "PENDING_EXECUTION"
        self._log_state(session, order.order_id, "PENDING_EXECUTION")
        
        # Simulate instant fill
        order.status = "FILLED"
        order.filled_quantity = order.quantity
        self._log_state(session, order.order_id, "FILLED")
        
        self._sync_position(session, order)
        session.commit()

        log_trade(
            "FILLED", order_id=order.order_id, symbol=order.symbol,
            direction=order.transaction_type, quantity=order.quantity,
            price=order.price, stop_loss=order.stop_loss, target=order.target,
            confidence=order.confidence, reason=order.reason, mode=order.mode,
            status="FILLED",
        )

        return self._order_to_result(order)

    def _execute_live(self, session, order: OrderModel) -> OrderResult:
        """Route order through Angel One SmartAPI with backoff retries."""
        order.status = "PENDING_EXECUTION"
        self._log_state(session, order.order_id, "PENDING_EXECUTION")
        session.commit()

        try:
            from app.connectors.smartapi_connector import SmartAPIConnector
            from app.services.instrument_master import get_token

            connector = SmartAPIConnector()
            connector._ensure_login()

            token = get_token(order.symbol)
            if not token:
                order.status = "REJECTED"
                order.error = f"Cannot resolve token for {order.symbol}"
                self._log_state(session, order.order_id, "REJECTED")
                session.commit()
                log_trade(
                    "REJECTED", order_id=order.order_id, symbol=order.symbol,
                    direction=order.transaction_type, mode=order.mode,
                    status="REJECTED", error=order.error,
                )
                return self._order_to_result(order)

            order_payload = {
                "variety": "NORMAL",
                "tradingsymbol": f"{order.symbol}-EQ",
                "symboltoken": token,
                "transactiontype": order.transaction_type,
                "exchange": "NSE",
                "ordertype": "LIMIT",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "price": str(order.price),
                "quantity": str(order.quantity),
            }

            # Exponential backoff retry loop (Max 3 retries)
            resp = None
            last_err = None
            for attempt in range(1, 4):
                try:
                    resp = connector.place_order(order_payload)
                    if resp and isinstance(resp, dict) and resp.get("status"):
                        break # Success
                    else:
                        last_err = resp.get("message", "Unknown SmartAPI error") if resp else "Empty response"
                        logger.warning(f"[LIVE] Order placement attempt {attempt} failed: {last_err}")
                except Exception as e:
                    last_err = str(e)
                    logger.warning(f"[LIVE] Order placement attempt {attempt} exception: {e}")
                
                if attempt < 3: # Backoff
                    time.sleep(2 ** attempt)

            if resp and isinstance(resp, dict) and resp.get("status"):
                broker_order_id = str(resp.get("data", {}).get("orderid", ""))
                order.status = "FILLED"
                order.filled_quantity = order.quantity
                self._log_state(session, order.order_id, "FILLED")
                self._sync_position(session, order)
                log_trade(
                    "FILLED", order_id=order.order_id, symbol=order.symbol,
                    direction=order.transaction_type, quantity=order.quantity,
                    price=order.price, stop_loss=order.stop_loss, target=order.target,
                    confidence=order.confidence, reason=order.reason,
                    mode=order.mode, status="FILLED",
                )
            else:
                order.status = "FAILED"
                order.error = last_err or "Exhausted all retries"
                self._log_state(session, order.order_id, "FAILED")
                log_trade(
                    "FAILED", order_id=order.order_id, symbol=order.symbol,
                    direction=order.transaction_type, mode=order.mode,
                    status="FAILED", error=order.error,
                )

            session.commit()
            return self._order_to_result(order)

        except Exception as e:
            logger.error(f"[LIVE] Critical failure routing order: {e}")
            order.status = "FAILED"
            order.error = str(e)
            self._log_state(session, order.order_id, "FAILED")
            session.commit()
            log_trade(
                "FAILED", order_id=order.order_id, symbol=order.symbol,
                direction=order.transaction_type, mode=order.mode,
                status="FAILED", error=str(e),
            )
            return self._order_to_result(order)

    def _sync_position(self, session, order: OrderModel):
        """Update or insert an open position into the database."""
        pos = session.query(PositionModel).filter_by(symbol=order.symbol).first()
        if pos:
            # Simple averaging/override logic for safety. In strict systems, calculate WAEP.
            if pos.direction == order.transaction_type:
                pos.quantity += order.quantity
                pos.target = order.target
                pos.stop_loss = order.stop_loss
            else:
                pos.quantity = abs(pos.quantity - order.quantity)
                if order.quantity > pos.quantity:
                    pos.direction = order.transaction_type
        else:
            pos = PositionModel(
                symbol=order.symbol,
                direction=order.transaction_type,
                quantity=order.quantity,
                entry_price=order.price,
                stop_loss=order.stop_loss,
                target=order.target
            )
            session.add(pos)
        logger.info(f"[DB-SYNC] Synced position for {order.symbol} (Qty={pos.quantity})")


    def close_position(self, symbol: str, exit_price: float) -> Optional[float]:
        """Close an open position from DB and calculate realized PnL."""
        db_gen = get_sync_db_session()
        session = next(db_gen)
        try:
            pos = session.query(PositionModel).filter_by(symbol=symbol).first()
            if not pos:
                return None

            if pos.direction == "BUY":
                pnl = (exit_price - pos.entry_price) * pos.quantity
            else:
                pnl = (pos.entry_price - exit_price) * pos.quantity

            # Remove position from active DB
            session.delete(pos)
            session.commit()
            
            logger.info(f"[ORDER] Closed {symbol}: Entry=₹{pos.entry_price:.2f} Exit=₹{exit_price:.2f} PnL=₹{pnl:,.2f}")

            # Audit log
            log_trade(
                "EXIT", order_id=f"EXIT-{symbol}", symbol=symbol,
                direction=pos.direction, quantity=pos.quantity,
                price=exit_price, mode=self.mode, status="CLOSED",
                pnl=round(pnl, 2),
            )

            return pnl
        finally:
            session.close()


    def has_position(self, symbol: str) -> bool:
        db_gen = get_sync_db_session()
        session = next(db_gen)
        try:
            pos = session.query(PositionModel).filter_by(symbol=symbol).first()
            return pos is not None and pos.quantity > 0
        finally:
            session.close()

    def get_position(self, symbol: str):
        db_gen = get_sync_db_session()
        session = next(db_gen)
        try:
            return session.query(PositionModel).filter_by(symbol=symbol).first()
        finally:
            session.close()

    def get_journal(self) -> list[dict]:
        db_gen = get_sync_db_session()
        session = next(db_gen)
        try:
            orders = session.query(OrderModel).order_by(OrderModel.timestamp.desc()).limit(20).all()
            return [
                {
                    "order_id": o.order_id, "symbol": o.symbol, "direction": o.transaction_type,
                    "quantity": o.quantity, "price": o.price, "status": o.status, "mode": o.mode,
                    "timestamp": str(o.timestamp), "error": o.error, "reason": o.reason
                } for o in orders
            ]
        finally:
            session.close()

    def get_open_positions(self) -> list[dict]:
        db_gen = get_sync_db_session()
        session = next(db_gen)
        try:
            positions = session.query(PositionModel).all()
            return [
                {"symbol": p.symbol, "direction": p.direction, "entry": p.entry_price, "qty": p.quantity,
                 "sl": p.stop_loss, "target": p.target}
                for p in positions
            ]
        finally:
            session.close()

    def sync_positions_with_broker(self) -> dict:
        """
        Compare DB positions with broker's actual positions.
        Returns a sync report for logging and monitoring.
        Only meaningful in LIVE mode.
        """
        report = {"status": "skipped", "mismatches": [], "db_count": 0, "broker_count": 0}

        if self.mode != "LIVE":
            return report

        try:
            from app.connectors.smartapi_connector import SmartAPIConnector
            connector = SmartAPIConnector()
            connector._ensure_login()

            broker_positions = connector.get_positions() or []
            db_positions = self.get_open_positions()

            report["db_count"] = len(db_positions)
            report["broker_count"] = len(broker_positions)
            report["status"] = "synced"

            db_syms = {p["symbol"] for p in db_positions}
            broker_syms = set()
            for bp in broker_positions:
                sym = bp.get("tradingsymbol", "").replace("-EQ", "")
                if sym:
                    broker_syms.add(sym)

            # Positions in DB but not at broker
            for sym in db_syms - broker_syms:
                mismatch = {"symbol": sym, "issue": "IN_DB_NOT_BROKER"}
                report["mismatches"].append(mismatch)
                logger.warning(f"[SYNC] Position mismatch: {sym} in DB but not at broker")

            # Positions at broker but not in DB
            for sym in broker_syms - db_syms:
                mismatch = {"symbol": sym, "issue": "IN_BROKER_NOT_DB"}
                report["mismatches"].append(mismatch)
                logger.warning(f"[SYNC] Position mismatch: {sym} at broker but not in DB")

            if not report["mismatches"]:
                logger.info(f"[SYNC] ✓ Positions in sync ({len(db_positions)} positions)")

        except Exception as e:
            logger.error(f"[SYNC] Broker sync failed: {e}")
            report["status"] = "error"
            report["error"] = str(e)

        return report

    def _order_to_result(self, o: OrderModel) -> OrderResult:
        return OrderResult(
            order_id=o.order_id, symbol=o.symbol, direction=o.transaction_type,
            quantity=o.quantity, price=o.price, stop_loss=o.stop_loss, target=o.target,
            status=o.status, mode=o.mode, timestamp=str(o.timestamp), error=o.error,
            reason=o.reason, confidence=o.confidence
        )
