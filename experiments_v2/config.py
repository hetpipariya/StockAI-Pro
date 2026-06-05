"""
experiments_v2/config.py — Centralized Configuration for StockAI Pro Pipeline
==============================================================================
Single source of truth for all hyperparameters, paths, and thresholds.
Both training scripts and the backend loader import from here.

Usage:
    from experiments_v2.config import Paths, LabelConfig, SimConfig, ModelConfig
"""
from __future__ import annotations

from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# PROJECT ROOT  (resolves correctly regardless of CWD)
# ─────────────────────────────────────────────────────────────────────────────
_HERE        = Path(__file__).resolve().parent          # experiments_v2/
PROJECT_ROOT = _HERE.parent                             # project root


# ─────────────────────────────────────────────────────────────────────────────
# DATA PATHS
# ─────────────────────────────────────────────────────────────────────────────
class DataPaths:
    RAW_1H = _HERE / "data" / "raw" / "1h"
    RAW_5M = _HERE / "data" / "raw" / "5m"
    RAW_1M = _HERE / "data" / "raw" / "1m"


# ─────────────────────────────────────────────────────────────────────────────
# MODEL OUTPUT PATHS  (dual-save: experiment + backend production)
# ─────────────────────────────────────────────────────────────────────────────
class ModelPaths:
    # Experiment storage (research & versioning)
    EXP_TREND_1H  = _HERE / "models" / "trend_1h"
    EXP_ENTRY_5M  = _HERE / "models" / "entry_5m"

    # Production backend storage (loaded by FastAPI at runtime)
    PROD_TREND_1H = PROJECT_ROOT / "backend" / "models" / "trend_1h"
    PROD_ENTRY_5M = PROJECT_ROOT / "backend" / "models" / "entry_5m"

    @classmethod
    def all_trend_1h(cls) -> list[Path]:
        return [cls.EXP_TREND_1H, cls.PROD_TREND_1H]

    @classmethod
    def all_entry_5m(cls) -> list[Path]:
        return [cls.EXP_ENTRY_5M, cls.PROD_ENTRY_5M]


# ─────────────────────────────────────────────────────────────────────────────
# 1H TREND MODEL — LABEL CONFIG
# ─────────────────────────────────────────────────────────────────────────────
class TrendLabelConfig:
    FUTURE_BARS  = 4        # 4 × 1h = 4h look-ahead
    BULL_THRESH  = 0.005    # +0.5% → BULL
    BEAR_THRESH  = -0.005   # -0.5% → BEAR


# ─────────────────────────────────────────────────────────────────────────────
# 5M ENTRY MODEL — LABEL CONFIG
# ─────────────────────────────────────────────────────────────────────────────
class EntryLabelConfig:
    FUTURE_BARS   = 6       # 6 × 5m = 30-minute horizon
    BUY_THRESH    = 0.005   # +0.5% → BUY
    SELL_THRESH   = -0.005  # -0.5% → SELL
    # |return| < 0.5% → HOLD (noise band)


# ─────────────────────────────────────────────────────────────────────────────
# TRADE SIMULATION PARAMETERS  (shared by both models)
# ─────────────────────────────────────────────────────────────────────────────
class SimConfig:
    TP_PCT       = 0.005    # 0.50% take-profit
    SL_PCT       = 0.0035   # 0.35% stop-loss  → RR ≈ 1.43
    SLIPPAGE_PCT = 0.0005   # 0.05% slippage per side

    # Per-timeframe max hold bars
    MAX_HOLD_1H  = 6        # 6h
    MAX_HOLD_5M  = 12       # 60 min


# ─────────────────────────────────────────────────────────────────────────────
# MODEL HYPERPARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
class ModelConfig:
    # ── 1h trend model ───────────────────────
    TREND_XGB = dict(
        objective             = "binary:logistic",
        n_estimators          = 600,
        max_depth             = 4,
        learning_rate         = 0.03,
        subsample             = 0.80,
        colsample_bytree      = 0.80,
        min_child_weight      = 8,
        gamma                 = 0.15,
        reg_alpha             = 0.1,
        reg_lambda            = 1.5,
        random_state          = 42,
        n_jobs                = -1,
        tree_method           = "hist",
        eval_metric           = "logloss",
        early_stopping_rounds = 50,
    )

    # ── 5m entry model ───────────────────────
    ENTRY_XGB = dict(
        objective             = "multi:softprob",
        num_class             = 3,
        n_estimators          = 700,
        max_depth             = 5,
        learning_rate         = 0.03,
        subsample             = 0.80,
        colsample_bytree      = 0.75,
        min_child_weight      = 15,
        gamma                 = 0.15,
        reg_alpha             = 0.15,
        reg_lambda            = 1.5,
        random_state          = 42,
        n_jobs                = -1,
        tree_method           = "hist",
        eval_metric           = "mlogloss",
        early_stopping_rounds = 50,
    )


# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE THRESHOLDS
# ─────────────────────────────────────────────────────────────────────────────
class InferenceConfig:
    # 1h: probability of BULL required to pass trend filter
    TREND_THRESHOLD  = 0.55

    # 5m: minimum class probability to issue a BUY or SELL signal
    ENTRY_BUY_THRESH  = 0.38
    ENTRY_SELL_THRESH = 0.38


# ─────────────────────────────────────────────────────────────────────────────
# PREDICTION RESPONSE SCHEMA  (used by backend API)
# ─────────────────────────────────────────────────────────────────────────────
def build_prediction_response(
    signal: str,
    confidence: float,
    entry_price: float,
) -> dict:
    """
    Build the standardized prediction payload returned by the backend.
    signal: 'BUY' | 'SELL' | 'HOLD'
    """
    tp = sl = None
    if signal == "BUY":
        tp = round(entry_price * (1 + SimConfig.TP_PCT), 2)
        sl = round(entry_price * (1 - SimConfig.SL_PCT), 2)
    elif signal == "SELL":
        tp = round(entry_price * (1 - SimConfig.TP_PCT), 2)
        sl = round(entry_price * (1 + SimConfig.SL_PCT), 2)

    return {
        "signal":     signal,
        "confidence": round(confidence, 4),
        "target":     tp,
        "stop_loss":  sl,
        "rr_ratio":   round(SimConfig.TP_PCT / SimConfig.SL_PCT, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# DATA LOADING CONFIG
# ─────────────────────────────────────────────────────────────────────────────
class DataConfig:
    TREND_MIN_ROWS = 180    # minimum bars per symbol for 1h model
    ENTRY_MIN_ROWS = 500    # minimum bars per symbol for 5m model
    FILL_GAPS      = True
    DROP_GAP_ROWS  = True


# ---------------------------------------------------------------------------
# PRODUCTION STRATEGY — FILTERING + RISK MANAGEMENT
# ---------------------------------------------------------------------------
class StrategyConfig:
    # Phase 1: Trend filter
    TREND_BULL_MIN  = 0.55   # P(BULL) >= 0.55 -> BULL regime
    TREND_BEAR_MAX  = 0.45   # P(BULL) <= 0.45 -> BEAR regime

    # Phase 2: Entry confidence gates
    ENTRY_BUY_MIN   = 0.35
    ENTRY_SELL_MIN  = 0.30

    # Phase 3: Quality filters
    MIN_ATR_PCT     = 0.003  # skip flat markets (ATR < 0.30%)
    MIN_VOL_RATIO   = 0.70   # skip low-volume bars
    COOLDOWN_BARS   = 3      # min bars between trades on same symbol

    # Phase 4: Risk management
    CAPITAL_INITIAL    = 1_000_000
    RISK_PER_TRADE_PCT = 0.005       # 0.5% risk per trade (conservative start)
    TP_PCT             = 0.005
    SL_PCT             = 0.0035
    SLIPPAGE_PCT       = 0.0005

    # Phase 5: Circuit-breakers
    MAX_TRADES_PER_DAY = 8
    DAILY_LOSS_LIMIT   = -0.03       # -3% daily equity -> stop for today
    DRAWDOWN_KILL      = -0.15       # -15% peak-to-trough -> shutdown
    MAX_HOLD_BARS      = 12

    @classmethod
    def position_size(cls, equity, entry):
        return (equity * cls.RISK_PER_TRADE_PCT) / (entry * cls.SL_PCT)

    @classmethod
    def rr_ratio(cls):
        return round(cls.TP_PCT / cls.SL_PCT, 2)
