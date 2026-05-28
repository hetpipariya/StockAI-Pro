"""
backend/app/strategy/signal_engine.py
======================================
Production Signal Engine for StockAI Pro.

Combines 1h trend model + 5m entry model with:
  - Phase 1: Trend filter (only trade with the trend)
  - Phase 2: Confidence gates (min probability thresholds)
  - Phase 3: Quality filters (ATR, volume, cooldown)

Designed for real-time FastAPI integration.
Call `SignalEngine.generate(symbol, bar_5m, latest_1h_proba)` per bar.

Prediction response format:
{
    "signal":     "BUY" | "SELL" | "HOLD",
    "confidence": 0.72,
    "reason":     "BULL trend + prob_buy=0.51 > 0.35",
    "target":     1234.50,
    "stop_loss":  1229.68,
    "qty":        162,
    "rr_ratio":   1.43,
    "blocked_by": None | "NEUTRAL_TREND" | "LOW_ATR" | "LOW_VOLUME" | "COOLDOWN" ...
}
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.strategy.config import SimConfig, StrategyConfig

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# DATA CONTRACTS
# ─────────────────────────────────────────────
@dataclass
class Bar5m:
    """Minimal 5m bar context required by SignalEngine."""
    symbol:        str
    timestamp:     datetime
    close:         float
    atr_pct:       float           # ATR as % of close (from feature engineering)
    volume_ratio:  float           # current vol / 20-bar avg vol
    prob_buy:      float           # P(BUY)  from SoftmaxCalibrator
    prob_sell:     float           # P(SELL) from SoftmaxCalibrator
    prob_hold:     float           # P(HOLD) from SoftmaxCalibrator


@dataclass
class TrendState:
    """Latest 1h model output for a symbol."""
    symbol:       str
    timestamp:    datetime
    prob_bull:    float            # P(BULL) from PlattCalibrator
    regime:       str = field(init=False)

    def __post_init__(self):
        if self.prob_bull >= StrategyConfig.TREND_BULL_MIN:
            self.regime = "BULL"
        elif self.prob_bull <= StrategyConfig.TREND_BEAR_MAX:
            self.regime = "BEAR"
        else:
            self.regime = "NEUTRAL"


@dataclass
class TradeSignal:
    """Signal returned to the backend API / order router."""
    signal:       str              # "BUY" | "SELL" | "HOLD"
    symbol:       str
    timestamp:    datetime
    entry_price:  float
    target:       float | None
    stop_loss:    float | None
    qty:          float            # position size in shares (use floor for live)
    confidence:   float            # strongest class probability
    regime:       str              # "BULL" | "BEAR" | "NEUTRAL"
    prob_buy:     float
    prob_sell:    float
    reason:       str
    blocked_by:   str | None       # None if live signal, else reason for HOLD
    rr_ratio:     float = field(default_factory=lambda: StrategyConfig.rr_ratio())


# ─────────────────────────────────────────────
# COOLDOWN TRACKER
# ─────────────────────────────────────────────
class CooldownTracker:
    """Per-symbol cooldown: enforces COOLDOWN_BARS between entries."""
    def __init__(self):
        self._last_trade_bar: dict[str, int] = {}   # symbol -> bar index
        self._bar_counter:    dict[str, int] = {}   # symbol -> total bars seen

    def tick(self, symbol: str) -> None:
        self._bar_counter[symbol] = self._bar_counter.get(symbol, 0) + 1

    def record_trade(self, symbol: str) -> None:
        self._last_trade_bar[symbol] = self._bar_counter.get(symbol, 0)

    def is_cooling_down(self, symbol: str) -> bool:
        last = self._last_trade_bar.get(symbol, -9999)
        current = self._bar_counter.get(symbol, 0)
        return (current - last) < StrategyConfig.COOLDOWN_BARS


# ─────────────────────────────────────────────
# SIGNAL ENGINE
# ─────────────────────────────────────────────
class SignalEngine:
    """
    Stateless core + per-instance cooldown state.
    Instantiate once per session (or per symbol if isolated).

    Usage (FastAPI):
        engine = SignalEngine(equity=portfolio.equity)
        signal = engine.generate(bar_5m, trend_state)
    """

    def __init__(self, equity: float = StrategyConfig.CAPITAL_INITIAL):
        self.equity    = equity
        self._cooldown = CooldownTracker()
        logger.info("SignalEngine initialized | equity=%.0f | RR=%.2f",
                    equity, StrategyConfig.rr_ratio())

    def update_equity(self, new_equity: float) -> None:
        """Call after every closed trade to keep position sizing current."""
        self.equity = new_equity

    # ── PHASE 1 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _trend_allows(regime: str, direction: str) -> bool:
        """Only BUY in BULL regime. Only SELL in BEAR regime."""
        if direction == "BUY":
            return regime == "BULL"
        if direction == "SELL":
            return regime == "BEAR"
        return False

    # ── PHASE 2 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _confidence_passes(bar: Bar5m, direction: str) -> bool:
        if direction == "BUY":
            return bar.prob_buy >= StrategyConfig.ENTRY_BUY_MIN
        if direction == "SELL":
            return bar.prob_sell >= StrategyConfig.ENTRY_SELL_MIN
        return False

    # ── PHASE 3 ──────────────────────────────────────────────────────────────
    @staticmethod
    def _quality_passes(bar: Bar5m) -> tuple[bool, str | None]:
        """Returns (passes, block_reason)."""
        if bar.atr_pct < StrategyConfig.MIN_ATR_PCT:
            return False, "LOW_ATR"
        if bar.volume_ratio < StrategyConfig.MIN_VOL_RATIO:
            return False, "LOW_VOLUME"
        return True, None

    def _cooldown_passes(self, symbol: str) -> tuple[bool, str | None]:
        if self._cooldown.is_cooling_down(symbol):
            return False, "COOLDOWN"
        return True, None

    # ── SIGNAL ASSEMBLY ───────────────────────────────────────────────────────
    def generate(self, bar: Bar5m, trend: TrendState) -> TradeSignal:
        """
        Main entry point. Call once per incoming 5m bar per symbol.
        Returns a TradeSignal with signal="HOLD" if all filters pass but
        no direction qualifies, or a BUY/SELL signal with full risk params.
        """
        self._cooldown.tick(bar.symbol)

        def hold(reason: str, blocked_by: str | None = None) -> TradeSignal:
            return TradeSignal(
                signal="HOLD", symbol=bar.symbol, timestamp=bar.timestamp,
                entry_price=bar.close, target=None, stop_loss=None,
                qty=0.0, confidence=bar.prob_hold,
                regime=trend.regime, prob_buy=bar.prob_buy, prob_sell=bar.prob_sell,
                reason=reason, blocked_by=blocked_by,
            )

        # ── Filter 1: Neutral regime → no trade ───────────────────────────
        if trend.regime == "NEUTRAL":
            return hold(
                f"Trend NEUTRAL (p_bull={trend.prob_bull:.2f})",
                blocked_by="NEUTRAL_TREND",
            )

        # ── Filter 2: Quality (ATR + volume) ──────────────────────────────
        quality_ok, block_reason = self._quality_passes(bar)
        if not quality_ok:
            return hold(f"Quality filter: {block_reason}", blocked_by=block_reason)

        # ── Filter 3: Cooldown ─────────────────────────────────────────────
        cool_ok, cool_reason = self._cooldown_passes(bar.symbol)
        if not cool_ok:
            return hold("In cooldown period", blocked_by=cool_reason)

        # ── Filter 4: Direction + trend alignment ──────────────────────────
        # Determine candidate direction from 5m model
        if bar.prob_buy > bar.prob_sell:
            candidate = "BUY"
            confidence = bar.prob_buy
        else:
            candidate = "SELL"
            confidence = bar.prob_sell

        trend_ok = self._trend_allows(trend.regime, candidate)
        conf_ok  = self._confidence_passes(bar, candidate)

        if not trend_ok:
            return hold(
                f"Counter-trend blocked: {candidate} rejected in {trend.regime} regime",
                blocked_by="COUNTER_TREND",
            )
        if not conf_ok:
            thresh = StrategyConfig.ENTRY_BUY_MIN if candidate == "BUY" else StrategyConfig.ENTRY_SELL_MIN
            return hold(
                f"Low confidence: p_{candidate.lower()}={confidence:.3f} < {thresh}",
                blocked_by="LOW_CONFIDENCE",
            )

        # ── All filters passed — build live signal ─────────────────────────
        self._cooldown.record_trade(bar.symbol)

        entry = bar.close
        direction_sign = 1 if candidate == "BUY" else -1

        tp = round(entry * (1 + direction_sign * StrategyConfig.TP_PCT), 2)
        sl = round(entry * (1 - direction_sign * StrategyConfig.SL_PCT), 2)
        qty = StrategyConfig.position_size(self.equity, entry)

        reason = (
            f"regime={trend.regime} (p_bull={trend.prob_bull:.2f}) | "
            f"p_{candidate.lower()}={confidence:.3f} >= "
            f"{'BUY' if candidate == 'BUY' else 'SELL'} gate | "
            f"atr={bar.atr_pct*100:.2f}% vol_ratio={bar.volume_ratio:.2f}"
        )

        logger.info(
            "[%s] %s @ %.2f | TP=%.2f SL=%.2f qty=%.0f conf=%.3f",
            bar.symbol, candidate, entry, tp, sl, qty, confidence,
        )

        return TradeSignal(
            signal=candidate, symbol=bar.symbol, timestamp=bar.timestamp,
            entry_price=entry, target=tp, stop_loss=sl,
            qty=qty, confidence=confidence,
            regime=trend.regime, prob_buy=bar.prob_buy, prob_sell=bar.prob_sell,
            reason=reason, blocked_by=None,
        )

    def to_api_response(self, signal: TradeSignal) -> dict:
        """Serialize to the standard backend API response format."""
        return {
            "signal":      signal.signal,
            "confidence":  round(signal.confidence, 4),
            "target":      signal.target,
            "stop_loss":   signal.stop_loss,
            "entry_price": signal.entry_price,
            "qty":         round(signal.qty, 2),
            "rr_ratio":    signal.rr_ratio,
            "regime":      signal.regime,
            "prob_buy":    round(signal.prob_buy, 4),
            "prob_sell":   round(signal.prob_sell, 4),
            "reason":      signal.reason,
            "blocked_by":  signal.blocked_by,
            "timestamp":   signal.timestamp.isoformat() if signal.timestamp else None,
        }
