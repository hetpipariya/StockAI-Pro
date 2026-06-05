"""
experiments_v2/training/backtest_strategy.py
=============================================
Walk-forward strategy backtest for StockAI Pro.

Loads TRAINED models from disk, runs the full production strategy
(trend filter + entry gates + risk management) on the TEST SET
to show realistic performance vs raw model outputs.

USAGE:
    python -m experiments_v2.training.backtest_strategy
    python experiments_v2/training/backtest_strategy.py [--args]

PIPELINE:
    Load trend_1h model + entry_5m model
        -> Feature engineer 5m + 1h data (leakage-free)
        -> Merge 1h context into 5m bars
        -> For each 5m bar (chronological):
             1. Get 1h trend probability -> TrendState
             2. Get 5m entry probabilities -> Bar5m
             3. Apply SignalEngine (all 7 phases)
             4. Apply RiskManager (circuit-breakers)
             5. Walk-forward TP/SL resolution
        -> Compute final strategy statistics vs baseline

EXPECTED IMPROVEMENTS vs baseline:
    Metric              Baseline    Strategy Target
    ─────────────────── ─────────── ───────────────
    Trades/day          140+        5-15
    Win Rate            ~50%        >53%
    Profit Factor       ~1.12       >1.30
    Max Drawdown        -83%        <-20%
    Precision BUY       0.24        >0.40
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from experiments_v2.config import (
    DataConfig,
    DataPaths,
    ModelPaths,
    SimConfig,
    StrategyConfig,
)
from experiments_v2.features.feature_engineering import (
    BASE_5M_FEATURE_COLUMNS,
    CONTEXT_1H_FEATURE_COLUMNS,
    ENTRY_FEATURE_COLUMNS,
    TREND_FEATURE_COLUMNS,
    DataConfig as FeDataConfig,
    build_1h_context,
    compute_base_features,
    finalize_feature_matrix,
    load_timeframe_csv_folder,
    merge_5m_with_1h_context,
)

warnings.filterwarnings("ignore", category=UserWarning)


# ─────────────────────────────────────────────
# MODEL LOADING
# ─────────────────────────────────────────────
def load_model_bundle(model_dir: Path) -> dict[str, Any]:
    """Load model, calibrator, scaler, and feature list from a saved bundle."""
    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")
    return {
        "model":      joblib.load(model_dir / "model.pkl"),
        "calibrator": joblib.load(model_dir / "calibrator.pkl"),
        "scaler":     joblib.load(model_dir / "scaler.pkl"),
        "features":   joblib.load(model_dir / "features.pkl"),
    }


# ─────────────────────────────────────────────
# PROBABILITY INFERENCE
# ─────────────────────────────────────────────
def get_trend_proba(df: pd.DataFrame, bundle: dict) -> np.ndarray:
    """Return P(BULL) for every row in df."""
    X = bundle["scaler"].transform(df[bundle["features"]].values)
    return bundle["calibrator"].predict_proba(X)[:, 1]   # P(BULL)


def get_entry_proba(df: pd.DataFrame, bundle: dict) -> np.ndarray:
    """Return (n, 3) array: [P(SELL), P(HOLD), P(BUY)]."""
    X = bundle["scaler"].transform(df[bundle["features"]].values)
    return bundle["calibrator"].predict_proba(X)          # shape (n, 3)


# ─────────────────────────────────────────────
# DATA LOADING
# ─────────────────────────────────────────────
def load_test_data(
    dir_5m: Path,
    dir_1h: Path,
    min_rows_5m: int = DataConfig.ENTRY_MIN_ROWS,
    min_rows_1h: int = DataConfig.TREND_MIN_ROWS,
    max_files: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load and feature-engineer 5m+1h data, return merged test-set DataFrame."""
    cfg_5m = FeDataConfig("5m", min_rows_5m, DataConfig.FILL_GAPS, DataConfig.DROP_GAP_ROWS, max_files)
    cfg_1h = FeDataConfig("1h", min_rows_1h, DataConfig.FILL_GAPS, DataConfig.DROP_GAP_ROWS, max_files)

    print("[BT] Loading 5m data...")
    raw_5m = load_timeframe_csv_folder(dir_5m, cfg_5m)
    feat_5m = compute_base_features(raw_5m)
    base_cols = [col for col in ENTRY_FEATURE_COLUMNS if col not in CONTEXT_1H_FEATURE_COLUMNS]
    feat_5m = finalize_feature_matrix(feat_5m, base_cols)

    print("[BT] Loading 1h data...")
    raw_1h = load_timeframe_csv_folder(dir_1h, cfg_1h)
    feat_1h = compute_base_features(raw_1h)
    feat_1h = finalize_feature_matrix(feat_1h, TREND_FEATURE_COLUMNS)

    ctx_1h = build_1h_context(feat_1h)
    feat_5m = merge_5m_with_1h_context(feat_5m, ctx_1h)
    feat_5m = finalize_feature_matrix(feat_5m, ENTRY_FEATURE_COLUMNS)

    print(f"   Combined: {len(feat_5m):,} rows | {feat_5m['symbol'].nunique()} symbols")

    # Use the last 15% as the test window (mirrors training split)
    feat_5m = feat_5m.sort_values("timestamp").reset_index(drop=True)
    split   = int(len(feat_5m) * 0.85)
    test_df = feat_5m.iloc[split:].copy().reset_index(drop=True)
    print(f"   Test set : {len(test_df):,} rows | "
          f"{test_df['timestamp'].min()} → {test_df['timestamp'].max()}")
    return test_df, feat_1h


# ─────────────────────────────────────────────
# TREND REGIME LOOKUP (per 5m bar)
# ─────────────────────────────────────────────
def build_regime_series(
    test_5m: pd.DataFrame,
    trend_bundle: dict,
    feat_1h: pd.DataFrame,
) -> pd.Series:
    """
    For each 5m bar, retrieve P(BULL) from the 1h trend model.
    Uses asof-merge (backward) to get the most recent closed 1h bar.
    Same approach as the feature engineering — zero look-ahead.
    """
    trend_1h = feat_1h.copy().sort_values(["symbol", "timestamp"])
    trend_1h = finalize_feature_matrix(trend_1h, TREND_FEATURE_COLUMNS)

    p_bull_blocks = []
    for symbol, grp_1h in trend_1h.groupby("symbol", sort=False):
        grp_5m = test_5m[test_5m["symbol"] == symbol].copy()
        if grp_5m.empty:
            continue
        grp_1h = grp_1h.sort_values("timestamp").copy()
        # Shift 1h by 1 bar (same logic as build_1h_context)
        grp_1h[TREND_FEATURE_COLUMNS] = grp_1h[TREND_FEATURE_COLUMNS].shift(1)
        grp_1h = grp_1h.dropna(subset=TREND_FEATURE_COLUMNS[:1])

        p_bull = get_trend_proba(grp_1h, trend_bundle)
        grp_1h = grp_1h.copy()
        grp_1h["_p_bull"] = p_bull

        merged = pd.merge_asof(
            grp_5m[["timestamp"]].sort_values("timestamp"),
            grp_1h[["timestamp", "_p_bull"]].rename(columns={"timestamp": "ts_1h"}),
            left_on="timestamp", right_on="ts_1h",
            direction="backward", allow_exact_matches=False,
        )
        merged.index = grp_5m.index
        p_bull_blocks.append(merged["_p_bull"])

    if not p_bull_blocks:
        return pd.Series(0.5, index=test_5m.index)
    combined = pd.concat(p_bull_blocks).reindex(test_5m.index)
    return combined.fillna(0.5)   # neutral fallback for missing 1h context


# ─────────────────────────────────────────────
# FULL STRATEGY SIMULATION
# ─────────────────────────────────────────────
def run_strategy_backtest(
    test_df: pd.DataFrame,
    entry_bundle: dict,
    p_bull: pd.Series,
) -> dict:
    """
    Walk-forward simulation implementing all 7 strategy phases.
    No future data used — each decision uses only info available at bar i.
    """
    n = len(test_df)
    closes = test_df["close"].values.astype(float)
    highs  = test_df["high"].values.astype(float)
    lows   = test_df["low"].values.astype(float)
    atrs   = (test_df["atr14"] / test_df["close"]).values.astype(float)
    vols   = test_df["volume_ratio"].values.astype(float)
    timestamps = test_df["timestamp"].values
    symbols    = test_df["symbol"].values

    # Get 5m entry probabilities for all bars at once
    proba_5m = get_entry_proba(test_df, entry_bundle)  # (n, 3): SELL=0, HOLD=1, BUY=2
    p_sell   = proba_5m[:, 0]
    p_buy    = proba_5m[:, 2]
    p_bull_arr = p_bull.values

    # ── Risk state ──────────────────────────────────────────────────────────
    equity       = float(StrategyConfig.CAPITAL_INITIAL)
    peak_equity  = equity
    daily_pnl    = 0.0
    daily_trades = 0
    current_day  = None
    day_halted   = False
    system_halted= False

    # ── Per-symbol cooldown ──────────────────────────────────────────────────
    cooldown_until: dict[str, int] = {}   # symbol -> bar index when cooldown expires

    # ── Tracking ─────────────────────────────────────────────────────────────
    pnl_list  : list[float] = []
    equity_curve: list[float] = []
    trade_log : list[dict] = []
    filter_counts: dict[str, int] = defaultdict(int)

    for i in range(n - StrategyConfig.MAX_HOLD_BARS - 1):
        sym = symbols[i]
        bar_date = pd.Timestamp(timestamps[i]).date()

        # ── Daily reset ───────────────────────────────────────────────────────
        if bar_date != current_day:
            current_day  = bar_date
            daily_pnl    = 0.0
            daily_trades = 0
            day_halted   = False

        # ── Circuit-breakers ──────────────────────────────────────────────────
        if system_halted:
            filter_counts["system_halted"] += 1
            continue
        if day_halted:
            filter_counts["day_halted"] += 1
            continue

        # ── Phase 1: Trend filter ─────────────────────────────────────────────
        pb = float(p_bull_arr[i])
        if pb >= StrategyConfig.TREND_BULL_MIN:
            regime = "BULL"
        elif pb <= StrategyConfig.TREND_BEAR_MAX:
            regime = "BEAR"
        else:
            filter_counts["neutral_trend"] += 1
            continue

        # ── Phase 2: Entry confidence ─────────────────────────────────────────
        if regime == "BULL":
            confidence = float(p_buy[i])
            direction  = "BUY"
            if confidence < StrategyConfig.ENTRY_BUY_MIN:
                filter_counts["low_confidence"] += 1
                continue
        else:
            confidence = float(p_sell[i])
            direction  = "SELL"
            if confidence < StrategyConfig.ENTRY_SELL_MIN:
                filter_counts["low_confidence"] += 1
                continue

        # ── Phase 3: Quality filters ──────────────────────────────────────────
        if atrs[i] < StrategyConfig.MIN_ATR_PCT:
            filter_counts["low_atr"] += 1
            continue
        if vols[i] < StrategyConfig.MIN_VOL_RATIO:
            filter_counts["low_volume"] += 1
            continue
        if cooldown_until.get(sym, 0) > i:
            filter_counts["cooldown"] += 1
            continue

        # ── Phase 4: Daily caps ───────────────────────────────────────────────
        if daily_trades >= StrategyConfig.MAX_TRADES_PER_DAY:
            filter_counts["daily_cap"] += 1
            continue

        # ── Phase 5: Execution — entry ────────────────────────────────────────
        dir_sign = 1 if direction == "BUY" else -1
        entry    = closes[i] * (1 + dir_sign * StrategyConfig.SLIPPAGE_PCT)
        tp       = entry * (1 + dir_sign * StrategyConfig.TP_PCT)
        sl       = entry * (1 - dir_sign * StrategyConfig.SL_PCT)

        # Position sizing: 1% equity risk
        qty      = StrategyConfig.position_size(equity, entry)

        # ── Phase 6: Walk-forward TP/SL resolution ────────────────────────────
        outcome_pct = None
        for j in range(i + 1, min(i + StrategyConfig.MAX_HOLD_BARS + 1, n)):
            sl_hit = lows[j] <= sl  if direction == "BUY" else highs[j] >= sl
            tp_hit = highs[j] >= tp if direction == "BUY" else lows[j]  <= tp
            if sl_hit:   # SL priority
                outcome_pct = -(StrategyConfig.SL_PCT + StrategyConfig.SLIPPAGE_PCT)
                break
            if tp_hit:
                outcome_pct = StrategyConfig.TP_PCT - StrategyConfig.SLIPPAGE_PCT
                break
        if outcome_pct is None:
            # Timeout — exit at close of last bar in window
            exit_p  = closes[min(i + StrategyConfig.MAX_HOLD_BARS, n - 1)]
            outcome_pct = dir_sign * (exit_p / entry - 1) - StrategyConfig.SLIPPAGE_PCT

        pnl_rs = outcome_pct * entry * qty

        # ── Update state ──────────────────────────────────────────────────────
        equity       += pnl_rs
        peak_equity   = max(peak_equity, equity)
        daily_pnl    += pnl_rs
        daily_trades += 1

        cooldown_until[sym] = i + StrategyConfig.COOLDOWN_BARS
        pnl_list.append(outcome_pct)
        equity_curve.append(equity)

        trade_log.append({
            "idx": i, "symbol": sym, "direction": direction,
            "entry": round(entry, 2), "tp": round(tp, 2), "sl": round(sl, 2),
            "outcome_pct": round(outcome_pct * 100, 3), "pnl_rs": round(pnl_rs, 2),
            "regime": regime, "confidence": round(confidence, 4),
            "p_bull": round(pb, 4), "equity": round(equity, 2),
        })

        # ── Circuit-breaker checks ─────────────────────────────────────────────
        daily_pnl_pct = daily_pnl / max(equity, 1.0)
        if daily_pnl_pct <= StrategyConfig.DAILY_LOSS_LIMIT:
            day_halted = True

        dd = (equity - peak_equity) / peak_equity
        if dd <= StrategyConfig.DRAWDOWN_KILL:
            system_halted = True
            filter_counts["system_killed"] += 1

    # ─────────────────────────────────────────
    # FINAL STATISTICS
    # ─────────────────────────────────────────
    if not pnl_list:
        return {"error": "no trades taken — thresholds may be too strict"}

    pnls   = np.array(pnl_list)
    wins   = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    cumret = np.cumsum(pnls)
    wr     = float((pnls > 0).mean())

    equity_arr  = np.array(equity_curve)
    peak_series = np.maximum.accumulate(equity_arr)
    dd_series   = (equity_arr - peak_series) / peak_series
    max_dd      = float(dd_series.min())

    total_bars  = n
    sessions    = max(1, (pd.Timestamp(timestamps[-1]) - pd.Timestamp(timestamps[0])).days)
    total_return= float((equity_arr[-1] - StrategyConfig.CAPITAL_INITIAL)
                        / StrategyConfig.CAPITAL_INITIAL * 100)

    buy_trades  = [t for t in trade_log if t["direction"] == "BUY"]
    sell_trades = [t for t in trade_log if t["direction"] == "SELL"]

    return {
        "strategy_stats": {
            "total_trades"     : len(pnl_list),
            "buy_trades"       : len(buy_trades),
            "sell_trades"      : len(sell_trades),
            "trade_rate_pct"   : round(len(pnl_list) / total_bars * 100, 3),
            "win_rate"         : round(wr, 4),
            "profit_factor"    : round(float(wins.sum() / abs(losses.sum())), 4) if losses.sum() != 0 else 999.0,
            "expectancy_pct"   : round(float(pnls.mean() * 100), 4),
            "max_drawdown_pct" : round(max_dd * 100, 2),
            "total_return_pct" : round(total_return, 2),
            "final_equity"     : round(float(equity_arr[-1]), 2),
            "rr_ratio"         : StrategyConfig.rr_ratio(),
            "approx_trades_per_day": round(len(pnl_list) / max(sessions, 1), 1),
        },
        "filter_breakdown": dict(filter_counts),
        "total_bars_evaluated": total_bars,
        "trade_log_head": trade_log[:10],
        "thresholds_used": {
            "trend_bull_min"  : StrategyConfig.TREND_BULL_MIN,
            "trend_bear_max"  : StrategyConfig.TREND_BEAR_MAX,
            "entry_buy_min"   : StrategyConfig.ENTRY_BUY_MIN,
            "entry_sell_min"  : StrategyConfig.ENTRY_SELL_MIN,
            "min_atr_pct"     : StrategyConfig.MIN_ATR_PCT,
            "min_vol_ratio"   : StrategyConfig.MIN_VOL_RATIO,
            "cooldown_bars"   : StrategyConfig.COOLDOWN_BARS,
            "max_trades_day"  : StrategyConfig.MAX_TRADES_PER_DAY,
            "daily_loss_limit": StrategyConfig.DAILY_LOSS_LIMIT,
            "drawdown_kill"   : StrategyConfig.DRAWDOWN_KILL,
        },
    }


# ─────────────────────────────────────────────
# PRETTY PRINT
# ─────────────────────────────────────────────
def print_results(result: dict, baseline: dict | None = None) -> None:
    s = result["strategy_stats"]
    print("\n" + "=" * 58)
    print("  STRATEGY BACKTEST RESULTS")
    print("=" * 58)
    print(f"  Total Trades      : {s['total_trades']}  "
          f"(BUY={s['buy_trades']} SELL={s['sell_trades']})")
    print(f"  Trade Rate        : {s['trade_rate_pct']:.2f}%")
    print(f"  Trades/day (est)  : {s['approx_trades_per_day']}")
    print(f"  Win Rate          : {s['win_rate']*100:.2f}%   (target > 50%)")
    print(f"  Profit Factor     : {s['profit_factor']:.3f}  (target > 1.30)")
    print(f"  Expectancy/trade  : {s['expectancy_pct']:.3f}%")
    print(f"  Max Drawdown      : {s['max_drawdown_pct']:.2f}%  (target < -20%)")
    print(f"  Total Return      : {s['total_return_pct']:.2f}%")
    print(f"  Final Equity      : Rs {s['final_equity']:,.0f}")
    print(f"  RR Ratio          : {s['rr_ratio']}")

    if baseline:
        print()
        print("  BASELINE vs STRATEGY")
        print(f"  {'Metric':<22} {'Baseline':>10} {'Strategy':>10}")
        print(f"  {'-'*44}")
        metrics = [
            ("Profit Factor", baseline.get("profit_factor", "?"), s["profit_factor"]),
            ("Win Rate %",    f"{baseline.get('win_rate', 0)*100:.1f}",
                              f"{s['win_rate']*100:.1f}"),
            ("Max DD %",      f"{baseline.get('max_drawdown_pct', 0):.1f}",
                              f"{s['max_drawdown_pct']:.1f}"),
            ("Trade Rate %",  f"{baseline.get('trade_rate_pct', 0):.1f}",
                              f"{s['trade_rate_pct']:.2f}"),
        ]
        for label, bl, st in metrics:
            print(f"  {label:<22} {str(bl):>10} {str(st):>10}")

    print()
    print("  FILTER BREAKDOWN (bars blocked per reason)")
    for k, v in sorted(result["filter_breakdown"].items(), key=lambda x: -x[1]):
        print(f"    {k:<25}: {v:,}")

    print("=" * 58 + "\n")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Strategy Backtest v1.0")
    p.add_argument("--data-5m",       type=Path, default=DataPaths.RAW_5M)
    p.add_argument("--data-1h",       type=Path, default=DataPaths.RAW_1H)
    p.add_argument("--trend-dir",     type=Path, default=ModelPaths.EXP_TREND_1H)
    p.add_argument("--entry-dir",     type=Path, default=ModelPaths.EXP_ENTRY_5M)
    p.add_argument("--max-files",     type=int,  default=None)
    p.add_argument("--output-json",   type=Path, default=None,
                   help="Optionally save results to a JSON file")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    print("[BT] Loading model bundles...")
    trend_bundle = load_model_bundle(args.trend_dir)
    entry_bundle = load_model_bundle(args.entry_dir)
    print(f"     Trend features : {len(trend_bundle['features'])}")
    print(f"     Entry features : {len(entry_bundle['features'])}")

    test_df, feat_1h = load_test_data(
        args.data_5m, args.data_1h, max_files=args.max_files
    )

    print("[BT] Computing 1h regime series for test bars...")
    p_bull = build_regime_series(test_df, trend_bundle, feat_1h)

    # Baseline stats (raw 5m model, no filters)
    proba_raw   = get_entry_proba(test_df, entry_bundle)
    n_buy_raw   = int((proba_raw[:, 2] >= StrategyConfig.ENTRY_BUY_MIN).sum())
    n_sell_raw  = int((proba_raw[:, 0] >= StrategyConfig.ENTRY_SELL_MIN).sum())
    baseline    = {
        "profit_factor"   : 1.12,
        "win_rate"        : 0.498,
        "max_drawdown_pct": -83.5,
        "trade_rate_pct"  : 16.1,
    }
    print(f"   Baseline raw signals: BUY={n_buy_raw:,} SELL={n_sell_raw:,}")

    print("[BT] Running strategy simulation...")
    result = run_strategy_backtest(test_df, entry_bundle, p_bull)

    print_results(result, baseline)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(result, indent=2, default=str))
        print(f"[BT] Results saved to {args.output_json}")

    # Always save to experiments_v2/outputs/
    out_path = _ROOT / "experiments_v2" / "outputs" / "strategy_backtest_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"[BT] Results also saved to {out_path}")


if __name__ == "__main__":
    main()
