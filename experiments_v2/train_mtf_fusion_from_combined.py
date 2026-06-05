from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


TIMEFRAME_1H = "1h"
TIMEFRAME_5M = "5m"

CONF_1H_MIN = 0.55
CONF_5M_MIN = 0.60

STOP_LOSS_PCT = 0.007
TAKE_PROFIT_PCT = 0.015
MAX_HOLDING_BARS = 6


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _load_model_payload(model_path: Path) -> dict[str, Any]:
    if not model_path.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")
    payload = joblib.load(model_path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected payload type for {model_path}")
    if "model" not in payload or "feature_columns" not in payload:
        raise RuntimeError(f"Payload missing required keys in {model_path}")
    return payload


def _prepare_timeframe_matrix(
    source_df: pd.DataFrame,
    timeframe: str,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = source_df[source_df["timeframe"].astype(str).str.lower() == timeframe].copy()
    if frame.empty:
        raise RuntimeError(f"No rows found for timeframe={timeframe}")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.dropna(subset=["timestamp", "symbol", "close", "high", "low"]).copy()

    for col in feature_columns:
        if col not in frame.columns:
            frame[col] = 0.0

        if pd.api.types.is_bool_dtype(frame[col]):
            frame[col] = frame[col].astype(np.int8)

        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    required_cols = ["close", "high", "low", *feature_columns]
    frame = frame.dropna(subset=required_cols).copy()
    frame = frame.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if frame.empty:
        raise RuntimeError(f"No usable rows remain for timeframe={timeframe} after preprocessing")

    matrix = frame[feature_columns].copy()
    return frame, matrix


def _predict_with_confidence(model: Any, matrix: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    prob_buy = model.predict_proba(matrix)[:, 1].astype(np.float32)
    pred = (prob_buy >= 0.5).astype(np.int32)
    conf = np.maximum(prob_buy, 1.0 - prob_buy).astype(np.float32)
    return pred, conf, prob_buy


def _merge_asof_by_symbol(
    left: pd.DataFrame,
    right: pd.DataFrame,
    right_columns: list[str],
) -> pd.DataFrame:
    merged_parts: list[pd.DataFrame] = []

    for symbol, left_group in left.groupby("symbol", sort=False):
        left_sorted = left_group.sort_values("timestamp").copy()
        right_sorted = right[right["symbol"] == symbol].sort_values("timestamp").copy()

        if right_sorted.empty:
            for col in right_columns:
                left_sorted[col] = np.nan
            merged_parts.append(left_sorted)
            continue

        merged = pd.merge_asof(
            left_sorted,
            right_sorted[["timestamp", *right_columns]],
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["symbol"] = symbol
        merged_parts.append(merged)

    if not merged_parts:
        return left.copy()

    out = pd.concat(merged_parts, ignore_index=True)
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def _simulate_trade_return(
    close_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    entry_idx: int,
    side: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
) -> float | None:
    last_idx = len(close_arr) - 1
    if entry_idx >= last_idx:
        return None

    entry_price = float(close_arr[entry_idx])
    if entry_price <= 0:
        return None

    if side == 1:
        tp = entry_price * (1.0 + take_profit_pct)
        sl = entry_price * (1.0 - stop_loss_pct)
    else:
        tp = entry_price * (1.0 - take_profit_pct)
        sl = entry_price * (1.0 + stop_loss_pct)

    end_idx = min(entry_idx + int(max_holding_bars), last_idx)
    for j in range(entry_idx + 1, end_idx + 1):
        bar_high = float(high_arr[j])
        bar_low = float(low_arr[j])

        if side == 1:
            hit_tp = bar_high >= tp
            hit_sl = bar_low <= sl
        else:
            hit_tp = bar_low <= tp
            hit_sl = bar_high >= sl

        # Conservative same-bar policy: stop is triggered first.
        if hit_tp and hit_sl:
            return -float(stop_loss_pct)
        if hit_sl:
            return -float(stop_loss_pct)
        if hit_tp:
            return float(take_profit_pct)

    exit_price = float(close_arr[end_idx])
    if exit_price <= 0:
        return None

    if side == 1:
        return float((exit_price / entry_price) - 1.0)
    return float((entry_price / exit_price) - 1.0)


def _backtest_strategy(
    frame: pd.DataFrame,
    pred_col: str,
    trade_col: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
) -> dict[str, Any]:
    returns: list[float] = []
    total_considered = 0
    total_signals = 0

    for _, group in frame.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True)
        if len(g) < 2:
            continue

        close_arr = g["close"].to_numpy(dtype=np.float64)
        high_arr = g["high"].to_numpy(dtype=np.float64)
        low_arr = g["low"].to_numpy(dtype=np.float64)
        pred_arr = g[pred_col].to_numpy(dtype=np.int32)
        trade_arr = g[trade_col].to_numpy(dtype=bool)

        total_considered += int(len(g) - 1)
        for i in range(len(g) - 1):
            if not trade_arr[i]:
                continue

            side = 1 if int(pred_arr[i]) == 1 else -1
            ret = _simulate_trade_return(
                close_arr=close_arr,
                high_arr=high_arr,
                low_arr=low_arr,
                entry_idx=i,
                side=side,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                max_holding_bars=max_holding_bars,
            )
            if ret is None:
                continue

            total_signals += 1
            returns.append(float(ret))

    skipped = int(max(total_considered - total_signals, 0))
    skipped_pct = float((skipped / max(total_considered, 1)) * 100.0)

    if total_signals > 0:
        ret_arr = np.asarray(returns, dtype=np.float64)
        win_rate = float(np.mean(ret_arr > 0))
        total_profit = float(np.sum(ret_arr))
        avg_profit = float(np.mean(ret_arr))
        gross_profit = float(np.sum(ret_arr[ret_arr > 0]))
        gross_loss_abs = float(abs(np.sum(ret_arr[ret_arr < 0])))
        profit_factor = float(gross_profit / gross_loss_abs) if gross_loss_abs > 0 else None

        equity = np.cumprod(1.0 + ret_arr)
        peak = np.maximum.accumulate(equity)
        drawdown = (equity - peak) / np.maximum(peak, 1e-12)
        max_drawdown = float(abs(np.min(drawdown))) if len(drawdown) else 0.0
    else:
        win_rate = 0.0
        total_profit = 0.0
        avg_profit = 0.0
        gross_profit = 0.0
        gross_loss_abs = 0.0
        profit_factor = None
        max_drawdown = 0.0

    return {
        "considered_samples": int(total_considered),
        "total_trades": int(total_signals),
        "skipped_trades": int(skipped),
        "pct_trades_skipped": skipped_pct,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "total_profit": total_profit,
        "avg_profit_per_trade": avg_profit,
        "gross_profit": gross_profit,
        "gross_loss_abs": gross_loss_abs,
    }


def run_fusion(
    dataset_path: Path,
    model_1h_path: Path,
    model_5m_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    payload_1h = _load_model_payload(model_1h_path)
    payload_5m = _load_model_payload(model_5m_path)

    model_1h = payload_1h["model"]
    model_5m = payload_5m["model"]
    features_1h = list(payload_1h["feature_columns"])
    features_5m = list(payload_5m["feature_columns"])

    df = pd.read_parquet(dataset_path)
    required = {"timestamp", "symbol", "timeframe", "close", "high", "low"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"Dataset missing required columns: {missing}")

    frame_1h, X_1h = _prepare_timeframe_matrix(df, TIMEFRAME_1H, features_1h)
    frame_5m, X_5m = _prepare_timeframe_matrix(df, TIMEFRAME_5M, features_5m)

    # Use out-of-sample 5m region (last 20%) for realistic comparison.
    split_5m = int(len(frame_5m) * 0.8)
    split_5m = max(1, min(len(frame_5m) - 1, split_5m))
    frame_5m_test = frame_5m.iloc[split_5m:].copy().reset_index(drop=True)
    X_5m_test = X_5m.iloc[split_5m:].copy().reset_index(drop=True)

    pred_1h, conf_1h, prob_1h = _predict_with_confidence(model_1h, X_1h)
    pred_5m, conf_5m, prob_5m = _predict_with_confidence(model_5m, X_5m_test)

    one_h_pred_frame = frame_1h[["timestamp", "symbol"]].copy()
    one_h_pred_frame["pred_1h"] = pred_1h
    one_h_pred_frame["conf_1h"] = conf_1h
    one_h_pred_frame["prob_buy_1h"] = prob_1h

    eval_frame = frame_5m_test[["timestamp", "symbol", "close", "high", "low"]].copy()
    eval_frame["pred_5m"] = pred_5m
    eval_frame["conf_5m"] = conf_5m
    eval_frame["prob_buy_5m"] = prob_5m

    eval_frame = _merge_asof_by_symbol(
        left=eval_frame,
        right=one_h_pred_frame,
        right_columns=["pred_1h", "conf_1h", "prob_buy_1h"],
    )
    eval_frame = eval_frame.dropna(subset=["pred_1h", "conf_1h"]).copy().reset_index(drop=True)
    eval_frame["pred_1h"] = eval_frame["pred_1h"].astype(np.int32)

    # Strategy masks.
    eval_frame["trade_1h_only"] = eval_frame["conf_1h"] >= CONF_1H_MIN
    eval_frame["trade_5m_only"] = eval_frame["conf_5m"] >= CONF_5M_MIN
    eval_frame["trade_fusion"] = (
        (eval_frame["conf_1h"] >= CONF_1H_MIN)
        & (eval_frame["conf_5m"] >= CONF_5M_MIN)
        & (eval_frame["pred_1h"] == eval_frame["pred_5m"])
    )
    eval_frame["pred_fusion"] = eval_frame["pred_5m"]

    stats_1h = _backtest_strategy(
        frame=eval_frame,
        pred_col="pred_1h",
        trade_col="trade_1h_only",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars=MAX_HOLDING_BARS,
    )
    stats_5m = _backtest_strategy(
        frame=eval_frame,
        pred_col="pred_5m",
        trade_col="trade_5m_only",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars=MAX_HOLDING_BARS,
    )
    stats_fusion = _backtest_strategy(
        frame=eval_frame,
        pred_col="pred_fusion",
        trade_col="trade_fusion",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars=MAX_HOLDING_BARS,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "mtf_fusion_backtest_report.json"
    aligned_path = output_dir / "mtf_fusion_aligned_predictions.csv"

    eval_frame.to_csv(aligned_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "models": {
            "model_1h": str(model_1h_path),
            "model_5m": str(model_5m_path),
        },
        "timeframes": {
            "trend": TIMEFRAME_1H,
            "entry": TIMEFRAME_5M,
        },
        "evaluation_window": {
            "rows_5m_test": int(len(frame_5m_test)),
            "rows_after_1h_alignment": int(len(eval_frame)),
            "start": str(eval_frame["timestamp"].min()) if not eval_frame.empty else None,
            "end": str(eval_frame["timestamp"].max()) if not eval_frame.empty else None,
        },
        "fusion_rules": {
            "long_condition": "1h BUY and 5m BUY",
            "short_condition": "1h SELL and 5m SELL",
            "otherwise": "NO TRADE",
            "confidence_1h_min": CONF_1H_MIN,
            "confidence_5m_min": CONF_5M_MIN,
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "max_holding_bars": MAX_HOLDING_BARS,
            "same_bar_policy": "conservative_stop_first",
        },
        "comparison": {
            "model_1h_only": stats_1h,
            "model_5m_only": stats_5m,
            "fusion_model": stats_fusion,
        },
        "artifacts": {
            "report": str(report_path),
            "aligned_predictions": str(aligned_path),
        },
    }

    report_path.write_text(json.dumps(_to_native(report), indent=2), encoding="utf-8")
    return _to_native(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Multi-timeframe fusion backtest using trained 1h trend and 5m entry models"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("experiments_v2/data/combined_dataset.parquet"),
        help="Combined parquet dataset path",
    )
    parser.add_argument(
        "--model-1h",
        type=Path,
        default=Path("experiments_v2/outputs/models/1h_trading_model/xgb_1h_trading_model.joblib"),
        help="Path to trained 1h model payload",
    )
    parser.add_argument(
        "--model-5m",
        type=Path,
        default=Path("experiments_v2/outputs/models/5m_profit_model/xgb_5m_profit_model.joblib"),
        help="Path to trained 5m model payload",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments_v2/outputs/reports"),
        help="Output directory for fusion report",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_fusion(
        dataset_path=args.dataset,
        model_1h_path=args.model_1h,
        model_5m_path=args.model_5m,
        output_dir=args.output_dir,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
