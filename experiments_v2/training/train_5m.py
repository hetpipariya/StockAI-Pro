"""
experiments_v2/training/train_5m.py — 5m Entry Model Training (Leakage-Free v3.0)
====================================================================================
USAGE:
    python -m experiments_v2.training.train_5m
    python experiments_v2/training/train_5m.py [--args]

PIPELINE:
    RAW 5m CSV  + RAW 1h CSV
        ↓ load_timeframe_csv_folder (each)
        ↓ compute_base_features (causal, per symbol)
        ↓ finalize_feature_matrix (drop NaN, contract check)
        ↓ build_1h_context (shift +1 bar → no current-hour leakage)
        ↓ merge_5m_with_1h_context (asof backward, allow_exact=False)
        ↓ build_entry_labels (pure forward-return, 30-min horizon)
        ↓ time_split (chronological 70/15/15)
        ↓ train XGBoost 3-class (early stopping on mlogloss)
        ↓ SoftmaxCalibrator (multinomial LR on valid, no re-training)
        ↓ evaluate (per-class ECE, precision, trade accuracy)
        ↓ simulate_profit (TP/SL walk-forward, SL-priority tie-break)
        ↓ DUAL SAVE → experiments_v2/models/entry_5m/ + backend/models/entry_5m/

CLASS ENCODING:
    SELL → 0  |  HOLD → 1  |  BUY → 2
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

# ── Ensure project root is importable ────────────────────────────────────────
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# ─────────────────────────────────────────────────────────────────────────────

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    precision_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from experiments_v2.config import (
    DataConfig,
    EntryLabelConfig,
    InferenceConfig,
    ModelConfig,
    ModelPaths,
    SimConfig,
    DataPaths,
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
    validate_feature_contract,
)
from experiments_v2.pipeline.production_validation import run_pretraining_validation

warnings.filterwarnings("ignore", category=UserWarning)

# Class encoding — XGBoost requires 0-indexed integers
CLASS_MAP   = {-1: 0, 0: 1, 1: 2}   # SELL→0, HOLD→1, BUY→2
CLASS_NAMES = {0: "SELL", 1: "HOLD", 2: "BUY"}


# ─────────────────────────────────────────────
# LABEL — PURE FORWARD RETURN
# ─────────────────────────────────────────────
def build_entry_labels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Label each 5m bar using PURE forward return over LABEL_FUTURE_BARS.
        BUY  (2) → future_return >= +BUY_THRESH
        SELL (0) → future_return <= -SELL_THRESH
        HOLD (1) → |future_return| < threshold  (noise band)

    TP/SL simulation is retained in simulate_profit() for backtesting ONLY.
    """
    close      = df["close"].astype(float).values
    n          = len(close)
    target_raw = np.zeros(n, dtype=np.int8)   # default 0 = HOLD before mapping

    for i in range(n - EntryLabelConfig.FUTURE_BARS):
        if close[i] == 0:
            continue
        fwd = close[i + EntryLabelConfig.FUTURE_BARS] / close[i] - 1.0
        if fwd >= EntryLabelConfig.BUY_THRESH:
            target_raw[i] = 1     # BUY (mapped to 2 via CLASS_MAP)
        elif fwd <= EntryLabelConfig.SELL_THRESH:
            target_raw[i] = -1    # SELL (mapped to 0 via CLASS_MAP)

    # Last N bars have no complete future window — trim
    out = df.copy()
    out["target_raw"] = target_raw
    out["target"]     = pd.Series(target_raw, index=df.index).map(CLASS_MAP).astype(int)
    out = out.iloc[: n - EntryLabelConfig.FUTURE_BARS].copy()
    return out


# ─────────────────────────────────────────────
# CHRONOLOGICAL SPLIT
# ─────────────────────────────────────────────
def time_split(
    frame: pd.DataFrame, train_frac: float = 0.70, valid_frac: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    n = len(ordered)
    t1, t2 = int(n * train_frac), int(n * (train_frac + valid_frac))
    return ordered.iloc[:t1].copy(), ordered.iloc[t1:t2].copy(), ordered.iloc[t2:].copy()


# ─────────────────────────────────────────────
# SOFTMAX CALIBRATOR — imported from shared module
# (stable pickle path: experiments_v2.training.calibrators)
# ─────────────────────────────────────────────
from experiments_v2.training.calibrators import SoftmaxCalibrator  # noqa: E402


# ─────────────────────────────────────────────
# TRAINING
# ─────────────────────────────────────────────
def train_and_calibrate(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
) -> tuple[XGBClassifier, SoftmaxCalibrator, StandardScaler]:
    X_train, y_train = train_df[feature_cols].values, train_df["target"].values
    X_valid, y_valid = valid_df[feature_cols].values, valid_df["target"].values

    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_valid_s = scaler.transform(X_valid)

    sw = compute_sample_weight("balanced", y_train)

    model = XGBClassifier(**ModelConfig.ENTRY_XGB)
    model.fit(
        X_train_s, y_train,
        sample_weight = sw,
        eval_set      = [(X_valid_s, y_valid)],
        verbose       = False,
    )
    print(f"   XGBoost best_iteration: {model.best_iteration}")

    calibrator = SoftmaxCalibrator(model)
    calibrator.fit(X_valid_s, y_valid)
    return model, calibrator, scaler


# ─────────────────────────────────────────────
# EVALUATION
# ─────────────────────────────────────────────
def evaluate(
    df: pd.DataFrame,
    calibrator: SoftmaxCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    buy_thresh: float,
    sell_thresh: float,
) -> dict:
    X      = scaler.transform(df[feature_cols].values)
    proba  = calibrator.predict_proba(X)   # [SELL=0, HOLD=1, BUY=2]
    y_true = df["target"].values

    pred = np.ones(len(y_true), dtype=int)
    pred[proba[:, 2] >= buy_thresh]  = 2
    pred[proba[:, 0] >= sell_thresh] = 0

    def ece_for_class(cls_idx: int) -> float:
        binary = (y_true == cls_idx).astype(int)
        fp, mp = calibration_curve(binary, proba[:, cls_idx], n_bins=10, strategy="quantile")
        return float(np.mean(np.abs(fp - mp)))

    trade_mask = pred != 1
    return {
        "accuracy_all"         : float(accuracy_score(y_true, pred)),
        "accuracy_trades_only" : float(accuracy_score(y_true[trade_mask], pred[trade_mask])) if trade_mask.sum() > 0 else 0.0,
        "trade_rate"           : float(trade_mask.mean()),
        "precision_buy"        : float(precision_score(y_true, pred, labels=[2], average="macro", zero_division=0)),
        "precision_sell"       : float(precision_score(y_true, pred, labels=[0], average="macro", zero_division=0)),
        "ece_buy"              : ece_for_class(2),
        "ece_sell"             : ece_for_class(0),
        "brier_buy"            : float(brier_score_loss((y_true == 2).astype(int), proba[:, 2])),
        "brier_sell"           : float(brier_score_loss((y_true == 0).astype(int), proba[:, 0])),
        "confusion_matrix"     : confusion_matrix(y_true, pred, labels=[0, 1, 2]).tolist(),
        "classification_report": classification_report(
            y_true, pred, labels=[0, 1, 2],
            target_names=["SELL", "HOLD", "BUY"], output_dict=True,
        ),
        "n_samples"  : int(len(y_true)),
        "n_traded"   : int(trade_mask.sum()),
        "thresholds" : {"buy": buy_thresh, "sell": sell_thresh},
    }


# ─────────────────────────────────────────────
# TP/SL SIMULATION
# ─────────────────────────────────────────────
def simulate_profit(
    df: pd.DataFrame,
    calibrator: SoftmaxCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    buy_thresh: float,
    sell_thresh: float,
) -> dict:
    """Walk-forward TP/SL simulation with SL-priority tie-break (conservative)."""
    X     = scaler.transform(df[feature_cols].values)
    proba = calibrator.predict_proba(X)
    closes = df["close"].values.astype(float)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    n      = len(closes)

    pnl_list = []
    for i in range(n - SimConfig.MAX_HOLD_5M - 1):
        buy_p, sell_p = proba[i, 2], proba[i, 0]
        if buy_p >= buy_thresh:
            direction = 1
        elif sell_p >= sell_thresh:
            direction = -1
        else:
            continue

        entry = closes[i] * (1 + direction * SimConfig.SLIPPAGE_PCT)
        tp = entry * (1 + direction * SimConfig.TP_PCT)
        sl = entry * (1 - direction * SimConfig.SL_PCT)
        outcome = 0.0
        for j in range(i + 1, min(i + SimConfig.MAX_HOLD_5M + 1, n)):
            sl_hit = lows[j] <= sl  if direction == 1 else highs[j] >= sl
            tp_hit = highs[j] >= tp if direction == 1 else lows[j]  <= tp
            if sl_hit:
                outcome = -(SimConfig.SL_PCT + SimConfig.SLIPPAGE_PCT)
                break
            if tp_hit:
                outcome = SimConfig.TP_PCT - SimConfig.SLIPPAGE_PCT
                break
        else:
            exit_price = closes[min(i + SimConfig.MAX_HOLD_5M, n - 1)]
            outcome = direction * (exit_price / entry - 1) - SimConfig.SLIPPAGE_PCT
        pnl_list.append(outcome)

    if not pnl_list:
        return {"error": "no trades taken"}

    pnls   = np.array(pnl_list)
    wins   = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    cumret = np.cumsum(pnls)
    wr     = float((pnls > 0).mean())

    return {
        "total_trades"    : len(pnls),
        "win_rate"        : wr,
        "profit_factor"   : float(wins.sum() / abs(losses.sum())) if losses.sum() != 0 else 999.0,
        "expectancy_pct"  : float((wr * wins.mean() + (1 - wr) * losses.mean()) * 100) if len(wins) and len(losses) else 0.0,
        "max_drawdown_pct": float((cumret - np.maximum.accumulate(cumret)).min() * 100),
        "total_return_pct": float(pnls.sum() * 100),
        "rr_ratio"        : round(SimConfig.TP_PCT / SimConfig.SL_PCT, 2),
        "sl_priority"     : True,
    }


# ─────────────────────────────────────────────
# DUAL SAVE
# ─────────────────────────────────────────────
def save_artifacts(
    model: XGBClassifier,
    calibrator: SoftmaxCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    metadata: dict,
) -> None:
    """Save to BOTH experiment storage and backend production directory."""
    for dest in ModelPaths.all_entry_5m():
        dest.mkdir(parents=True, exist_ok=True)
        joblib.dump(model,        dest / "model.pkl")
        joblib.dump(calibrator,   dest / "calibrator.pkl")
        joblib.dump(scaler,       dest / "scaler.pkl")
        joblib.dump(feature_cols, dest / "features.pkl")
        (dest / "feature_list.json").write_text(json.dumps(feature_cols, indent=2))
        if "pretraining_validation" in metadata:
            (dest / "validation_report.json").write_text(
                json.dumps(metadata["pretraining_validation"], indent=2, default=str)
            )
        (dest / "training_metadata.json").write_text(
            json.dumps(metadata, indent=2, default=str)
        )
        print(f"   [OK] Saved to: {dest}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train 5m Entry Model v3.0")
    p.add_argument("--data-5m",        type=Path,  default=DataPaths.RAW_5M)
    p.add_argument("--data-1h",        type=Path,  default=DataPaths.RAW_1H)
    p.add_argument("--buy-threshold",  type=float, default=InferenceConfig.ENTRY_BUY_THRESH)
    p.add_argument("--sell-threshold", type=float, default=InferenceConfig.ENTRY_SELL_THRESH)
    p.add_argument("--min-rows-5m",    type=int,   default=DataConfig.ENTRY_MIN_ROWS)
    p.add_argument("--min-rows-1h",    type=int,   default=DataConfig.TREND_MIN_ROWS)
    p.add_argument("--max-files",      type=int,   default=None)
    p.add_argument("--no-1h-context",  action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"[5m] 5m data: {args.data_5m}")
    print(f"[5m] 1h data: {args.data_1h}")

    cfg_5m = FeDataConfig("5m", args.min_rows_5m, DataConfig.FILL_GAPS, DataConfig.DROP_GAP_ROWS, args.max_files)
    cfg_1h = FeDataConfig("1h", args.min_rows_1h, DataConfig.FILL_GAPS, DataConfig.DROP_GAP_ROWS, args.max_files)

    # Load 5m
    raw_5m  = load_timeframe_csv_folder(args.data_5m, cfg_5m)
    print(f"   5m: {len(raw_5m):,} rows | {raw_5m['symbol'].nunique()} symbols")
    feat_5m = compute_base_features(raw_5m)
    base_5m_cols = list(set(ENTRY_FEATURE_COLUMNS) - set(CONTEXT_1H_FEATURE_COLUMNS))
    feat_5m = finalize_feature_matrix(feat_5m, base_5m_cols)

    # Merge 1h context
    if not args.no_1h_context:
        raw_1h  = load_timeframe_csv_folder(args.data_1h, cfg_1h)
        feat_1h = compute_base_features(raw_1h)
        feat_1h = finalize_feature_matrix(feat_1h, TREND_FEATURE_COLUMNS)
        ctx_1h  = build_1h_context(feat_1h)
        feat_5m = merge_5m_with_1h_context(feat_5m, ctx_1h)
        use_features = ENTRY_FEATURE_COLUMNS
        print(f"   After 1h merge: {len(feat_5m):,} rows")
    else:
        use_features = BASE_5M_FEATURE_COLUMNS

    feat_5m = finalize_feature_matrix(feat_5m, use_features)
    print(f"   Clean rows: {len(feat_5m):,}")

    # Label
    print("[5m] Building forward-return labels...")
    blocks = []
    for sym, grp in feat_5m.groupby("symbol", sort=False):
        blocks.append(build_entry_labels(grp.sort_values("timestamp")))
    labeled_df = pd.concat(blocks, ignore_index=True).sort_values(["symbol", "timestamp"])
    vc = labeled_df["target_raw"].value_counts().to_dict()
    print(f"   BUY={vc.get(1,0):,}  HOLD={vc.get(0,0):,}  SELL={vc.get(-1,0):,}")

    validate_feature_contract(labeled_df, use_features, context="train_5m:pre_split")

    train_df, valid_df, test_df = time_split(labeled_df)
    print(f"   Train={len(train_df):,} | Valid={len(valid_df):,} | Test={len(test_df):,}")

    validation_df = labeled_df.rename(columns={"target": "target_class"})
    validation_train = train_df.rename(columns={"target": "target_class"})
    validation_test = test_df.rename(columns={"target": "target_class"})
    validation_report = run_pretraining_validation(
        full_df=validation_df,
        train_df=validation_train,
        test_df=validation_test,
        feature_columns=use_features,
        required_timeframes=["5m"],
        strict=True,
    )

    print("[5m] Training + SoftmaxCalibrator...")
    model, calibrator, scaler = train_and_calibrate(train_df, valid_df, use_features)

    print("[5m] Evaluating...")
    metrics = evaluate(test_df, calibrator, scaler, use_features, args.buy_threshold, args.sell_threshold)
    sim     = simulate_profit(test_df, calibrator, scaler, use_features, args.buy_threshold, args.sell_threshold)

    print("\n" + "=" * 46)
    print("  [CLASSIFICATION]")
    print(f"  Accuracy (all)   : {metrics['accuracy_all']:.3f}")
    print(f"  Accuracy (trades): {metrics['accuracy_trades_only']:.3f}")
    print(f"  Trade Rate       : {metrics['trade_rate']*100:.2f}%")
    print(f"  Precision BUY    : {metrics['precision_buy']:.3f}")
    print(f"  Precision SELL   : {metrics['precision_sell']:.3f}")
    print(f"  ECE (BUY)        : {metrics['ece_buy']:.4f}  (< 0.05)")
    print(f"  ECE (SELL)       : {metrics['ece_sell']:.4f}  (< 0.05)")
    print()
    print("  [TRADING — primary criteria]")
    if "error" not in sim:
        print(f"  Trades     : {sim['total_trades']}")
        print(f"  Win Rate   : {sim['win_rate']*100:.2f}%  (target > 50%)")
        print(f"  PF         : {sim['profit_factor']:.2f}    (target > 1.30)")
        print(f"  MaxDD      : {sim['max_drawdown_pct']:.2f}%")
    print("=" * 46 + "\n")

    metadata = {
        "pipeline"       : "train_5m_v3_leakage_free",
        "model_type"     : "ENTRY_MODEL",
        "timeframe"      : "5m",
        "classes"        : CLASS_NAMES,
        "feature_count"  : len(use_features),
        "feature_list"   : use_features,
        "has_1h_context" : not args.no_1h_context,
        "label_config"   : {
            "type"             : "forward_return_fixed_horizon",
            "future_bars"      : EntryLabelConfig.FUTURE_BARS,
            "buy_threshold_pct": EntryLabelConfig.BUY_THRESH * 100,
            "sell_threshold_pct": abs(EntryLabelConfig.SELL_THRESH) * 100,
        },
        "sim_config" : {
            "tp_pct"       : SimConfig.TP_PCT * 100,
            "sl_pct"       : SimConfig.SL_PCT * 100,
            "slippage_pct" : SimConfig.SLIPPAGE_PCT * 100,
            "max_hold_bars": SimConfig.MAX_HOLD_5M,
            "sl_priority"  : True,
        },
        "inference_thresholds": {"buy": args.buy_threshold, "sell": args.sell_threshold},
        "calibration_method"  : "softmax_logistic_regression",
        "train_rows"          : len(train_df),
        "valid_rows"          : len(valid_df),
        "test_rows"           : len(test_df),
        "test_metrics"        : metrics,
        "profit_simulation"   : sim,
        "pretraining_validation": validation_report,
        "zero_fill_allowed"   : False,
        "feature_contract_v"  : "v3.0",
        "feature_version"     : "v3.0_cpp_canonical_20",
    }

    print("[5m] Saving artifacts (experiment + backend)...")
    save_artifacts(model, calibrator, scaler, use_features, metadata)
    print("[5m] DONE.\n")
    print(json.dumps({"test_metrics": metrics, "profit_simulation": sim}, indent=2, default=str))


if __name__ == "__main__":
    main()
