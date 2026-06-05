"""
experiments_v2/training/train_1h.py — 1H Trend Model Training (Leakage-Free v3.0)
====================================================================================
USAGE:
    python -m experiments_v2.training.train_1h
    python experiments_v2/training/train_1h.py [--args]

PIPELINE:
    RAW CSV DATA
        ↓ load_timeframe_csv_folder (gap-fill, clean)
        ↓ compute_base_features (causal indicators only)
        ↓ finalize_feature_matrix (drop NaN rows, contract validation)
        ↓ build_trend_labels (pure forward-return, no EMA gate)
        ↓ time_split (chronological 70/15/15)
        ↓ train XGBoost (early stopping on valid logloss)
        ↓ PlattCalibrator (LR on valid set — no re-training)
        ↓ evaluate (trading-focused metrics)
        ↓ simulate_profit (TP/SL walk-forward with slippage)
        ↓ DUAL SAVE → experiments_v2/models/trend_1h/ + backend/models/trend_1h/

LEAKAGE FIXES (v3.0):
    - Label: pure forward-return, no EMA gate (removes circular dependency)
    - Calibration: manual Platt scaling via LogisticRegression on held-out valid
    - Scaler: fit on train only
    - Split: strictly chronological — no shuffle
    - Early stopping: prevents overfitting on n_estimators
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

# ── Ensure project root is importable when running as a script ────────────────
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
    roc_auc_score,
)
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from experiments_v2.config import (
    DataConfig,
    ModelPaths,
    SimConfig,
    TrendLabelConfig,
    ModelConfig,
    InferenceConfig,
    DataPaths,
)
from experiments_v2.features.feature_engineering import (
    TREND_FEATURE_COLUMNS,
    DataConfig as FeDataConfig,
    compute_base_features,
    finalize_feature_matrix,
    load_timeframe_csv_folder,
    validate_feature_contract,
)
from experiments_v2.pipeline.production_validation import run_pretraining_validation

warnings.filterwarnings("ignore", category=UserWarning)


# ─────────────────────────────────────────────
# LABEL CONSTRUCTION — PURE FORWARD RETURN
# ─────────────────────────────────────────────
def build_trend_labels(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Label each 1h bar using PURE forward return over LABEL_FUTURE_BARS.
        BULL (1) → future_return >= +BULL_THRESH
        BEAR (0) → future_return <= -BEAR_THRESH
        NaN      → noise band — DROPPED (not trained on)

    WHY this is leakage-free:
    - Label uses close[i+N] which is never a feature.
    - No EMA dependency removes the circular: ema_spread feature → ema_gate label.
    """
    blocks: list[pd.DataFrame] = []
    for _, group in frame.groupby("symbol", sort=False):
        g     = group.sort_values("timestamp").copy()
        close = g["close"].astype(float)
        fwd   = close.shift(-TrendLabelConfig.FUTURE_BARS) / close - 1.0
        target = pd.Series(np.nan, index=g.index)
        target[fwd >= TrendLabelConfig.BULL_THRESH]  = 1
        target[fwd <= TrendLabelConfig.BEAR_THRESH]  = 0
        g["target"] = target
        g = g.dropna(subset=["target"]).copy()
        g["target"] = g["target"].astype(int)
        blocks.append(g)
    if not blocks:
        raise RuntimeError("build_trend_labels: no labeled data produced")
    return pd.concat(blocks, ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)


# ─────────────────────────────────────────────
# CHRONOLOGICAL SPLIT
# ─────────────────────────────────────────────
def time_split(
    frame: pd.DataFrame, train_frac: float = 0.70, valid_frac: float = 0.15
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Strictly chronological. NEVER shuffle time-series data."""
    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    n  = len(ordered)
    t1 = int(n * train_frac)
    t2 = int(n * (train_frac + valid_frac))
    return ordered.iloc[:t1].copy(), ordered.iloc[t1:t2].copy(), ordered.iloc[t2:].copy()


# ─────────────────────────────────────────────
# PLATT CALIBRATOR — imported from shared module
# (stable pickle path: experiments_v2.training.calibrators)
# ─────────────────────────────────────────────
from experiments_v2.training.calibrators import PlattCalibrator  # noqa: E402


# ─────────────────────────────────────────────
# TRAINING
# ─────────────────────────────────────────────
def train_and_calibrate(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
) -> tuple[XGBClassifier, PlattCalibrator, StandardScaler]:
    X_train, y_train = train_df[feature_cols].values, train_df["target"].values
    X_valid, y_valid = valid_df[feature_cols].values, valid_df["target"].values

    scaler    = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_valid_s = scaler.transform(X_valid)

    sw = compute_sample_weight("balanced", y_train)

    model = XGBClassifier(**ModelConfig.TREND_XGB)
    model.fit(
        X_train_s, y_train,
        sample_weight = sw,
        eval_set      = [(X_valid_s, y_valid)],
        verbose       = False,
    )
    print(f"   XGBoost best_iteration: {model.best_iteration}")

    calibrator = PlattCalibrator(model)
    calibrator.fit(X_valid_s, y_valid)
    return model, calibrator, scaler


# ─────────────────────────────────────────────
# EVALUATION
# ─────────────────────────────────────────────
def evaluate(
    df: pd.DataFrame,
    calibrator: PlattCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    threshold: float,
) -> dict:
    X      = scaler.transform(df[feature_cols].values)
    y_true = df["target"].values
    proba  = calibrator.predict_proba(X)[:, 1]
    pred   = (proba >= threshold).astype(int)

    traded = (proba >= threshold) | (proba <= (1 - threshold))
    frac_pos, mean_pred = calibration_curve(y_true, proba, n_bins=10, strategy="quantile")
    ece = float(np.mean(np.abs(frac_pos - mean_pred)))

    return {
        "accuracy"           : float(accuracy_score(y_true, pred)),
        "precision_bull"     : float(precision_score(y_true, pred, pos_label=1, zero_division=0)),
        "precision_bear"     : float(precision_score(y_true, pred, pos_label=0, zero_division=0)),
        "roc_auc"            : float(roc_auc_score(y_true, proba)),
        "brier_score"        : float(brier_score_loss(y_true, proba)),
        "ece"                : ece,
        "trade_rate"         : float(traded.mean()),
        "trade_accuracy"     : float(accuracy_score(y_true[traded], pred[traded])) if traded.sum() > 0 else 0.0,
        "confusion_matrix"   : confusion_matrix(y_true, pred, labels=[0, 1]).tolist(),
        "classification_report": classification_report(
            y_true, pred, labels=[0, 1],
            target_names=["BEAR", "BULL"], output_dict=True,
        ),
        "n_samples"          : int(len(y_true)),
        "n_traded"           : int(traded.sum()),
        "threshold_used"     : threshold,
    }


# ─────────────────────────────────────────────
# PROFIT SIMULATION
# ─────────────────────────────────────────────
def simulate_profit(
    df: pd.DataFrame,
    calibrator: PlattCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    threshold: float,
) -> dict:
    X      = scaler.transform(df[feature_cols].values)
    proba  = calibrator.predict_proba(X)[:, 1]
    closes = df["close"].values.astype(float)
    highs  = df["high"].values.astype(float)
    lows   = df["low"].values.astype(float)
    n      = len(closes)

    pnl_list = []
    for i in range(n - SimConfig.MAX_HOLD_1H - 1):
        p = proba[i]
        if threshold > p > (1 - threshold):
            continue
        direction = 1 if p >= threshold else -1
        entry = closes[i] * (1 + direction * SimConfig.SLIPPAGE_PCT)
        tp = entry * (1 + direction * SimConfig.TP_PCT)
        sl = entry * (1 - direction * SimConfig.SL_PCT)
        outcome = 0.0
        for j in range(i + 1, min(i + SimConfig.MAX_HOLD_1H + 1, n)):
            sl_hit = lows[j] <= sl if direction == 1 else highs[j] >= sl
            tp_hit = highs[j] >= tp if direction == 1 else lows[j] <= tp
            if sl_hit:
                outcome = -(SimConfig.SL_PCT + SimConfig.SLIPPAGE_PCT)
                break
            if tp_hit:
                outcome = SimConfig.TP_PCT - SimConfig.SLIPPAGE_PCT
                break
        else:
            exit_price = closes[min(i + SimConfig.MAX_HOLD_1H, n - 1)]
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
    }


# ─────────────────────────────────────────────
# DUAL SAVE
# ─────────────────────────────────────────────
def save_artifacts(
    model: XGBClassifier,
    calibrator: PlattCalibrator,
    scaler: StandardScaler,
    feature_cols: list[str],
    metadata: dict,
) -> None:
    """Save to BOTH experiment storage and backend production directory."""
    for dest in ModelPaths.all_trend_1h():
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
    p = argparse.ArgumentParser(description="Train 1h Trend Model v3.0")
    p.add_argument("--data-dir",   type=Path, default=DataPaths.RAW_1H)
    p.add_argument("--threshold",  type=float, default=InferenceConfig.TREND_THRESHOLD)
    p.add_argument("--min-rows",   type=int,   default=DataConfig.TREND_MIN_ROWS)
    p.add_argument("--max-files",  type=int,   default=None)
    return p.parse_args()


def main() -> None:
    args = parse_args()
    print(f"[1h] Data dir: {args.data_dir}")

    cfg = FeDataConfig(
        timeframe             = "1h",
        min_rows_per_symbol   = args.min_rows,
        fill_missing_timestamps = DataConfig.FILL_GAPS,
        drop_gap_filled_rows  = DataConfig.DROP_GAP_ROWS,
        max_files             = args.max_files,
    )

    raw  = load_timeframe_csv_folder(args.data_dir, cfg)
    print(f"   Loaded {len(raw):,} rows | {raw['symbol'].nunique()} symbols")

    feat = compute_base_features(raw)
    feat = finalize_feature_matrix(feat, TREND_FEATURE_COLUMNS)
    print(f"   After feature engineering: {len(feat):,} rows")

    labeled = build_trend_labels(feat)
    vc = labeled["target"].value_counts().to_dict()
    print(f"   After labeling: {len(labeled):,} rows | BULL={vc.get(1,0)} BEAR={vc.get(0,0)}")

    validate_feature_contract(labeled, TREND_FEATURE_COLUMNS, context="train_1h:pre_split")

    train_df, valid_df, test_df = time_split(labeled)
    print(f"   Train={len(train_df):,} | Valid={len(valid_df):,} | Test={len(test_df):,}")

    validation_df = labeled.rename(columns={"target": "target_class"})
    validation_train = train_df.rename(columns={"target": "target_class"})
    validation_test = test_df.rename(columns={"target": "target_class"})
    validation_report = run_pretraining_validation(
        full_df=validation_df,
        train_df=validation_train,
        test_df=validation_test,
        feature_columns=TREND_FEATURE_COLUMNS,
        required_timeframes=["1h"],
        strict=True,
    )

    print("[1h] Training + Platt calibration...")
    model, calibrator, scaler = train_and_calibrate(train_df, valid_df, TREND_FEATURE_COLUMNS)

    print("[1h] Evaluating...")
    metrics = evaluate(test_df, calibrator, scaler, TREND_FEATURE_COLUMNS, args.threshold)
    sim     = simulate_profit(test_df, calibrator, scaler, TREND_FEATURE_COLUMNS, args.threshold)

    print("\n" + "=" * 46)
    print("  [CLASSIFICATION]")
    print(f"  Accuracy   : {metrics['accuracy']:.3f}   (target 50-65%)")
    print(f"  ROC-AUC    : {metrics['roc_auc']:.3f}   (target 0.55-0.70)")
    print(f"  Brier      : {metrics['brier_score']:.4f}")
    print(f"  ECE        : {metrics['ece']:.4f}   (< 0.05 = calibrated)")
    print(f"  Trade Rate : {metrics['trade_rate']*100:.1f}%")
    print()
    print("  [TRADING — primary criteria]")
    if "error" not in sim:
        print(f"  Trades     : {sim['total_trades']}")
        print(f"  Win Rate   : {sim['win_rate']*100:.2f}%  (target > 50%)")
        print(f"  PF         : {sim['profit_factor']:.2f}    (target > 1.30)")
        print(f"  MaxDD      : {sim['max_drawdown_pct']:.2f}%")
    print("=" * 46 + "\n")

    metadata = {
        "pipeline"       : "train_1h_v3_leakage_free",
        "model_type"     : "TREND_FILTER",
        "timeframe"      : "1h",
        "classes"        : {0: "BEAR", 1: "BULL"},
        "feature_count"  : len(TREND_FEATURE_COLUMNS),
        "feature_list"   : TREND_FEATURE_COLUMNS,
        "label_config"   : {
            "type"              : "pure_forward_return",
            "future_bars"       : TrendLabelConfig.FUTURE_BARS,
            "bull_threshold_pct": TrendLabelConfig.BULL_THRESH * 100,
            "bear_threshold_pct": abs(TrendLabelConfig.BEAR_THRESH) * 100,
        },
        "sim_config"         : {
            "tp_pct"    : SimConfig.TP_PCT * 100,
            "sl_pct"    : SimConfig.SL_PCT * 100,
            "slippage"  : SimConfig.SLIPPAGE_PCT * 100,
            "max_hold_bars": SimConfig.MAX_HOLD_1H,
        },
        "inference_threshold": args.threshold,
        "calibration_method" : "platt_logistic_regression",
        "train_rows"         : len(train_df),
        "valid_rows"         : len(valid_df),
        "test_rows"          : len(test_df),
        "test_metrics"       : metrics,
        "profit_simulation"  : sim,
        "pretraining_validation": validation_report,
        "zero_fill_allowed"  : False,
        "feature_contract_v" : "v3.0",
        "feature_version"    : "v3.0_cpp_canonical_20",
        "leakage_fixes"      : [
            "Label: pure forward-return, no EMA gate",
            "Calibration: PlattCalibrator (LR on valid, base model not re-trained)",
            "1h context shifted +1 bar before merge",
            "allow_exact_matches=False in asof merge",
            "early_stopping_rounds prevents n_estimators overfitting",
            "Scaler fit on train only",
        ],
    }

    print("[1h] Saving artifacts to BOTH experiment and backend locations...")
    save_artifacts(model, calibrator, scaler, TREND_FEATURE_COLUMNS, metadata)
    print("[1h] DONE.\n")
    print(json.dumps({"test_metrics": metrics, "profit_simulation": sim}, indent=2, default=str))


if __name__ == "__main__":
    main()
