"""
Production Signal Engine & Risk Integration
============================================

Implements production-grade signal filtering with:
1. Trend gating (only trade aligned with 1h trend)
2. Multi-timeframe confirmation
3. Volume confirmation
4. Confidence threshold filtering
5. ATR-based stop-loss sizing
6. Dynamic target calculation
7. Risk-reward ratio validation
8. Position sizing

This is the CRITICAL system between raw model predictions and actual trades.

Version: v1.0
Updated: 2026-05-12
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────────────────
# CONSTANTS & ENUMS
# ────────────────────────────────────────────────────────────────────────────

SIGNAL_VERSION = "v1.0"

# Confidence thresholds (0.0-1.0)
MIN_CONFIDENCE_FOR_TRADE = 0.60  # Minimum confidence to generate BUY/SELL
CONFIDENCE_FOR_HOLD = 0.40  # Below this, force HOLD

# Trend alignment requirements
TREND_BULL_THRESHOLD = 0.55  # Need > 55% prob for BULL
TREND_BEAR_THRESHOLD = 0.45  # Need < 45% prob for BEAR

# Risk-reward requirements
MIN_RISK_REWARD_RATIO = 1.5  # Minimum RR ratio

# ATR-based stop-loss
ATR_MULTIPLIER_FOR_SL = 1.5  # Stop loss = close - (1.5 × ATR)
ATR_MULTIPLIER_FOR_TARGET = 3.0  # Dynamic target = entry + (3.0 × ATR) for BUY

# Volume requirements
MIN_VOLUME_RATIO = 0.5  # Don't trade if volume_ratio < 0.5

# Position sizing
MAX_POSITION_SIZE_PCT = 0.20  # Max 20% of equity per trade
BASE_POSITION_SIZE_PCT = 0.10  # Default 10% per trade

# Volatility filters
LOW_ATR_THRESHOLD = 0.001  # Skip if ATR < 0.1% of close (no volatility)
HIGH_ATR_THRESHOLD = 0.10  # Skip if ATR > 10% of close (too risky)

# Market hours (9:15 AM to 3:30 PM IST)
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30


class SignalType(Enum):
    """Signal types."""
    BUY = 1
    SELL = -1
    HOLD = 0


class BlockReason(Enum):
    """Reasons why a signal was blocked (converted to HOLD)."""
    NONE = "NONE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    TREND_MISMATCH = "TREND_MISMATCH"
    MTF_MISMATCH = "MTF_MISMATCH"
    LOW_VOLUME = "LOW_VOLUME"
    LOW_ATR = "LOW_ATR"
    HIGH_ATR = "HIGH_ATR"
    BAD_RR_RATIO = "BAD_RR_RATIO"
    OUTSIDE_HOURS = "OUTSIDE_HOURS"
    NIFTY_MISMATCH = "NIFTY_MISMATCH"
    VOLATILITY_REGIME = "VOLATILITY_REGIME"


# ────────────────────────────────────────────────────────────────────────────
# DATA STRUCTURES
# ────────────────────────────────────────────────────────────────────────────


@dataclass
class TradeSignal:
    """Complete trade signal from the engine."""
    signal: SignalType
    confidence: float
    entry_price: float
    stop_loss: float
    target: float
    position_size: float
    position_size_pct: float
    risk_reward_ratio: float
    timestamp: datetime
    reason: str
    blocked_by: Optional[BlockReason] = None
    
    # Supporting data
    rsi: float = 0.0
    macd_hist: float = 0.0
    atr_pct: float = 0.0
    volume_ratio: float = 1.0
    trend_state: str = "NEUTRAL"
    mtf_alignment: str = "NEUTRAL"
    nifty_state: str = "NEUTRAL"
    
    def is_buy(self) -> bool:
        return self.signal == SignalType.BUY
    
    def is_sell(self) -> bool:
        return self.signal == SignalType.SELL
    
    def is_hold(self) -> bool:
        return self.signal == SignalType.HOLD
    
    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        return {
            "signal": self.signal.name,
            "confidence": round(self.confidence, 3),
            "entry": round(self.entry_price, 2),
            "stop_loss": round(self.stop_loss, 2),
            "target": round(self.target, 2),
            "position_size": round(self.position_size, 0),
            "position_size_pct": round(self.position_size_pct, 1),
            "risk_reward_ratio": round(self.risk_reward_ratio, 2),
            "reason": self.reason,
            "blocked_by": self.blocked_by.value if self.blocked_by else None,
            "rsi": round(self.rsi, 1),
            "macd_hist": round(self.macd_hist, 4),
            "atr_pct": round(self.atr_pct, 4),
            "volume_ratio": round(self.volume_ratio, 2),
        }


@dataclass
class TrendState:
    """State of trending market."""
    regime: str = "NEUTRAL"  # BULL, BEAR, NEUTRAL
    strength: float = 0.5  # 0-1
    ema_9_above_21: bool = False
    ema_21_above_50: bool = False
    
    def is_bull(self) -> bool:
        return self.regime == "BULL"
    
    def is_bear(self) -> bool:
        return self.regime == "BEAR"
    
    def is_neutral(self) -> bool:
        return self.regime == "NEUTRAL"


# ────────────────────────────────────────────────────────────────────────────
# TREND DETECTION
# ────────────────────────────────────────────────────────────────────────────


def detect_trend_state(
    ema_9: float,
    ema_21: float,
    ema_50: float,
    close: float,
) -> TrendState:
    """
    Detect current trend state.
    
    BULL: EMA9 > EMA21 > EMA50
    BEAR: EMA9 < EMA21 < EMA50
    NEUTRAL: Otherwise
    """
    ema_9_above_21 = ema_9 > ema_21
    ema_21_above_50 = ema_21 > ema_50
    close_above_ema21 = close > ema_21
    
    if ema_9_above_21 and ema_21_above_50 and close_above_ema21:
        strength = (ema_9 - ema_21) / (ema_21 + 1e-10)
        return TrendState(
            regime="BULL",
            strength=min(1.0, strength),
            ema_9_above_21=True,
            ema_21_above_50=True,
        )
    elif not ema_9_above_21 and not ema_21_above_50 and not close_above_ema21:
        strength = (ema_21 - ema_9) / (ema_21 + 1e-10)
        return TrendState(
            regime="BEAR",
            strength=min(1.0, strength),
            ema_9_above_21=False,
            ema_21_above_50=False,
        )
    else:
        return TrendState(regime="NEUTRAL", strength=0.5)


# ────────────────────────────────────────────────────────────────────────────
# SIGNAL GENERATION FROM MODEL PREDICTIONS
# ────────────────────────────────────────────────────────────────────────────


def convert_model_prediction_to_signal(
    model_class: int,  # 1=BUY, 0=HOLD, -1=SELL
    confidence: float,
    entry_price: float,
    features: dict,
    trend: TrendState,
    mtf_alignment: str,
    nifty_state: str,
    capital: float = 100000.0,
    timestamp: Optional[datetime] = None,
) -> TradeSignal:
    """
    Convert raw model prediction to actionable trade signal with full validation.
    
    Args:
        model_class: Raw model output (1, 0, -1)
        confidence: Model confidence (0.0-1.0)
        entry_price: Current close price
        features: Dict with feature values (rsi, atr, volume_ratio, etc)
        trend: Current TrendState
        mtf_alignment: "BULL", "BEAR", "NEUTRAL"
        nifty_state: "BULL", "BEAR", "NEUTRAL"
        capital: Available capital for position sizing
        timestamp: Trade timestamp
    
    Returns:
        TradeSignal with all validations applied
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    initial_signal = SignalType(model_class)
    block_reason = None
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 1: Confidence threshold
    # ───────────────────────────────────────────────────────────────
    
    if confidence < CONFIDENCE_FOR_HOLD:
        block_reason = BlockReason.LOW_CONFIDENCE
        final_signal = SignalType.HOLD
    elif confidence < MIN_CONFIDENCE_FOR_TRADE:
        # Between HOLD and MIN_TRADE → force HOLD
        block_reason = BlockReason.LOW_CONFIDENCE
        final_signal = SignalType.HOLD
    else:
        final_signal = initial_signal
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 2: Trend alignment
    # ───────────────────────────────────────────────────────────────
    
    if final_signal != SignalType.HOLD:
        if final_signal == SignalType.BUY and not trend.is_bull():
            block_reason = BlockReason.TREND_MISMATCH
            final_signal = SignalType.HOLD
        elif final_signal == SignalType.SELL and not trend.is_bear():
            block_reason = BlockReason.TREND_MISMATCH
            final_signal = SignalType.HOLD
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 3: Multi-timeframe confirmation
    # ───────────────────────────────────────────────────────────────
    
    if final_signal != SignalType.HOLD:
        if final_signal == SignalType.BUY and mtf_alignment != "BULL":
            block_reason = BlockReason.MTF_MISMATCH
            final_signal = SignalType.HOLD
        elif final_signal == SignalType.SELL and mtf_alignment != "BEAR":
            block_reason = BlockReason.MTF_MISMATCH
            final_signal = SignalType.HOLD
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 4: Volume confirmation
    # ───────────────────────────────────────────────────────────────
    
    volume_ratio = features.get("volume_ratio_20", 1.0)
    if final_signal != SignalType.HOLD and volume_ratio < MIN_VOLUME_RATIO:
        block_reason = BlockReason.LOW_VOLUME
        final_signal = SignalType.HOLD
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 5: ATR filters (volatility regime)
    # ───────────────────────────────────────────────────────────────
    
    atr = features.get("atr_14", 0.0)
    atr_pct = atr / entry_price if entry_price > 0 else 0.0
    
    if final_signal != SignalType.HOLD:
        if atr_pct < LOW_ATR_THRESHOLD:
            block_reason = BlockReason.LOW_ATR
            final_signal = SignalType.HOLD
        elif atr_pct > HIGH_ATR_THRESHOLD:
            block_reason = BlockReason.HIGH_ATR
            final_signal = SignalType.HOLD
    
    # ───────────────────────────────────────────────────────────────
    # Calculate stop-loss and target
    # ───────────────────────────────────────────────────────────────
    
    stop_loss = _calculate_stop_loss(entry_price, atr, final_signal)
    target = _calculate_target(entry_price, atr, final_signal)
    
    # ───────────────────────────────────────────────────────────────
    # FILTER 6: Risk-reward ratio
    # ───────────────────────────────────────────────────────────────
    
    rr_ratio = _calculate_risk_reward_ratio(entry_price, stop_loss, target)
    
    if final_signal != SignalType.HOLD and rr_ratio < MIN_RISK_REWARD_RATIO:
        block_reason = BlockReason.BAD_RR_RATIO
        final_signal = SignalType.HOLD
    
    # ───────────────────────────────────────────────────────────────
    # Calculate position size
    # ───────────────────────────────────────────────────────────────
    
    position_size_pct = BASE_POSITION_SIZE_PCT
    
    # Reduce size if low confidence (but still trading)
    if final_signal != SignalType.HOLD and confidence < 0.70:
        position_size_pct *= 0.75
    
    # Cap at maximum
    position_size_pct = min(position_size_pct, MAX_POSITION_SIZE_PCT)
    
    position_size = (capital * position_size_pct) / entry_price if entry_price > 0 else 0
    
    # ───────────────────────────────────────────────────────────────
    # Build reason string
    # ───────────────────────────────────────────────────────────────
    
    reason = _build_reason_string(
        signal=final_signal,
        initial_signal=initial_signal,
        confidence=confidence,
        trend=trend,
        mtf_alignment=mtf_alignment,
        nifty_state=nifty_state,
        rsi=features.get("rsi_14", 50.0),
        volume_ratio=volume_ratio,
        atr_pct=atr_pct,
    )
    
    # ───────────────────────────────────────────────────────────────
    # Return complete signal
    # ───────────────────────────────────────────────────────────────
    
    return TradeSignal(
        signal=final_signal,
        confidence=confidence,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=target,
        position_size=position_size,
        position_size_pct=position_size_pct,
        risk_reward_ratio=rr_ratio,
        timestamp=timestamp,
        reason=reason,
        blocked_by=block_reason,
        rsi=features.get("rsi_14", 50.0),
        macd_hist=features.get("macd_histogram", 0.0),
        atr_pct=atr_pct,
        volume_ratio=volume_ratio,
        trend_state=trend.regime,
        mtf_alignment=mtf_alignment,
        nifty_state=nifty_state,
    )


# ────────────────────────────────────────────────────────────────────────────
# STOP-LOSS & TARGET CALCULATION
# ────────────────────────────────────────────────────────────────────────────


def _calculate_stop_loss(entry: float, atr: float, signal: SignalType) -> float:
    """
    Calculate ATR-based stop-loss.
    
    BUY: entry - (1.5 × ATR)
    SELL: entry + (1.5 × ATR)
    """
    if signal == SignalType.BUY:
        return entry - (ATR_MULTIPLIER_FOR_SL * atr)
    elif signal == SignalType.SELL:
        return entry + (ATR_MULTIPLIER_FOR_SL * atr)
    else:
        return entry  # HOLD


def _calculate_target(entry: float, atr: float, signal: SignalType) -> float:
    """
    Calculate dynamic target based on ATR.
    
    BUY: entry + (3.0 × ATR)
    SELL: entry - (3.0 × ATR)
    """
    if signal == SignalType.BUY:
        return entry + (ATR_MULTIPLIER_FOR_TARGET * atr)
    elif signal == SignalType.SELL:
        return entry - (ATR_MULTIPLIER_FOR_TARGET * atr)
    else:
        return entry  # HOLD


def _calculate_risk_reward_ratio(entry: float, stop_loss: float, target: float) -> float:
    """Calculate risk-reward ratio."""
    if entry == 0 or stop_loss == entry:
        return 0.0
    
    risk = abs(entry - stop_loss)
    reward = abs(target - entry)
    
    if risk == 0:
        return 0.0
    
    return reward / risk


# ────────────────────────────────────────────────────────────────────────────
# REASON STRING BUILDING
# ────────────────────────────────────────────────────────────────────────────


def _build_reason_string(
    signal: SignalType,
    initial_signal: SignalType,
    confidence: float,
    trend: TrendState,
    mtf_alignment: str,
    nifty_state: str,
    rsi: float,
    volume_ratio: float,
    atr_pct: float,
) -> str:
    """Build human-readable reason for signal."""
    if signal == SignalType.BUY:
        parts = [
            f"BUY: Conf={confidence:.0%}",
            f"Trend={trend.regime}",
            f"MTF={mtf_alignment}",
            f"RSI={rsi:.0f}",
        ]
        return " | ".join(parts)
    
    elif signal == SignalType.SELL:
        parts = [
            f"SELL: Conf={confidence:.0%}",
            f"Trend={trend.regime}",
            f"MTF={mtf_alignment}",
            f"RSI={rsi:.0f}",
        ]
        return " | ".join(parts)
    
    else:  # HOLD
        if initial_signal != SignalType.HOLD:
            parts = [
                f"HOLD: Blocked signal {initial_signal.name}",
                f"Conf={confidence:.0%}",
                f"Trend={trend.regime}",
                f"VolRatio={volume_ratio:.2f}",
            ]
        else:
            parts = [
                f"HOLD: No signal",
                f"Conf={confidence:.0%}",
                f"RSI={rsi:.0f}",
                f"ATR%={atr_pct:.2%}",
            ]
        return " | ".join(parts)


# ────────────────────────────────────────────────────────────────────────────
# UTILITIES
# ────────────────────────────────────────────────────────────────────────────


def is_market_hours(timestamp: Optional[datetime] = None) -> bool:
    """Check if within market trading hours (9:15-15:30 IST)."""
    if timestamp is None:
        timestamp = datetime.now()
    
    # Ignore date, just check time
    market_open = timestamp.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    market_close = timestamp.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    
    return market_open <= timestamp <= market_close


def get_signal_summary(signal: TradeSignal) -> str:
    """Get short summary of signal."""
    return (
        f"{signal.signal.name} @ {signal.entry_price:.2f} "
        f"| SL: {signal.stop_loss:.2f} | TGT: {signal.target:.2f} "
        f"| RR: {signal.risk_reward_ratio:.2f}x | Conf: {signal.confidence:.0%}"
    )
