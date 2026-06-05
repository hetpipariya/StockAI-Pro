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
TIMEFRAME_1M = "1m"

CONF_1H_MIN = 0.55
CONF_5M_MIN = 0.60

STOP_LOSS_PCT = 0.005
TAKE_PROFIT_PCT = 0.015
MAX_HOLDING_BARS_5M = 5
MAX_HOLDING_BARS_1M = MAX_HOLDING_BARS_5M * 5

MICRO_ENTRY_WINDOW_MINUTES = 5
PULLBACK_TOLERANCE = 0.001
RSI_BUY_MAX = 30.0
RSI_SELL_MIN = 70.0
VOLUME_SPIKE_THRESHOLD = 1.5


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


def _prepare_model_frame(
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
        raise RuntimeError(f"No usable rows remain for timeframe={timeframe}")

    matrix = frame[feature_columns].copy()
    return frame, matrix


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-12)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def _prepare_micro_frame(
    source_df: pd.DataFrame,
    volume_spike_threshold: float,
) -> pd.DataFrame:
    frame = source_df[source_df["timeframe"].astype(str).str.lower() == TIMEFRAME_1M].copy()
    if frame.empty:
        raise RuntimeError("No rows found for timeframe=1m")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.dropna(subset=["timestamp", "symbol", "close", "high", "low", "volume"]).copy()

    for col in ["close", "high", "low", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = frame.dropna(subset=["close", "high", "low", "volume"]).copy()
    frame = frame.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if "ema_20" in frame.columns:
        frame["ema_20_entry"] = pd.to_numeric(frame["ema_20"], errors="coerce")
    else:
        frame["ema_20_entry"] = (
            frame.groupby("symbol", sort=False)["close"]
            .transform(lambda s: s.ewm(span=20, adjust=False).mean())
            .astype(np.float64)
        )

    if "rsi" in frame.columns:
        frame["rsi_entry"] = pd.to_numeric(frame["rsi"], errors="coerce")
    else:
        frame["rsi_entry"] = frame.groupby("symbol", sort=False)["close"].transform(_compute_rsi)

    if "volume_ratio_20" in frame.columns:
        frame["volume_spike_score"] = pd.to_numeric(frame["volume_ratio_20"], errors="coerce")
    elif "volume_zscore_20" in frame.columns:
        frame["volume_spike_score"] = pd.to_numeric(frame["volume_zscore_20"], errors="coerce")
    else:
        roll_mean = frame.groupby("symbol", sort=False)["volume"].transform(
            lambda s: s.rolling(20, min_periods=20).mean()
        )
        frame["volume_spike_score"] = frame["volume"] / np.maximum(roll_mean, 1e-12)

    frame["volume_spike"] = frame["volume_spike_score"] >= float(volume_spike_threshold)
    frame = frame.dropna(subset=["ema_20_entry", "rsi_entry", "volume_spike_score"]).copy()
    frame = frame.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if frame.empty:
        raise RuntimeError("No usable 1m rows remain after micro feature preparation")
    return frame


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


def _simulate_trade_return_with_exit(
    close_arr: np.ndarray,
    high_arr: np.ndarray,
    low_arr: np.ndarray,
    entry_idx: int,
    side: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
) -> tuple[float | None, int]:
    last_idx = len(close_arr) - 1
    if entry_idx >= last_idx:
        return None, entry_idx

    entry_price = float(close_arr[entry_idx])
    if entry_price <= 0:
        return None, entry_idx

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

        # Conservative same-bar rule: stop first.
        if hit_tp and hit_sl:
            return -float(stop_loss_pct), j
        if hit_sl:
            return -float(stop_loss_pct), j
        if hit_tp:
            return float(take_profit_pct), j

    exit_price = float(close_arr[end_idx])
    if exit_price <= 0:
        return None, end_idx

    if side == 1:
        return float((exit_price / entry_price) - 1.0), end_idx
    return float((entry_price / exit_price) - 1.0), end_idx


def _summarize_performance(
    returns: list[float],
    considered_samples: int,
    candidate_signals: int,
    executed_trades: int,
    blocked_or_rejected: int,
) -> dict[str, Any]:
    if executed_trades > 0:
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

    skipped_trades = int(max(candidate_signals - executed_trades, 0))
    skipped_pct = float((skipped_trades / max(candidate_signals, 1)) * 100.0)

    return {
        "considered_samples": int(considered_samples),
        "candidate_signals": int(candidate_signals),
        "total_trades": int(executed_trades),
        "skipped_trades": int(skipped_trades),
        "pct_signals_skipped": skipped_pct,
        "blocked_or_rejected_signals": int(blocked_or_rejected),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "total_profit": total_profit,
        "avg_profit_per_trade": avg_profit,
        "gross_profit": gross_profit,
        "gross_loss_abs": gross_loss_abs,
    }


def _backtest_5m_execution(
    frame: pd.DataFrame,
    pred_col: str,
    trade_col: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
) -> dict[str, Any]:
    returns: list[float] = []
    considered = 0
    candidates = 0
    executed = 0
    blocked = 0

    for _, group in frame.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True)
        if len(g) < 2:
            continue

        close_arr = g["close"].to_numpy(dtype=np.float64)
        high_arr = g["high"].to_numpy(dtype=np.float64)
        low_arr = g["low"].to_numpy(dtype=np.float64)
        pred_arr = g[pred_col].to_numpy(dtype=np.int32)
        trade_arr = g[trade_col].to_numpy(dtype=bool)

        considered += int(len(g) - 1)
        active_until_idx = -1
        for i in range(len(g) - 1):
            if not bool(trade_arr[i]):
                continue
            candidates += 1

            if i <= active_until_idx:
                blocked += 1
                continue

            side = 1 if int(pred_arr[i]) == 1 else -1
            ret, exit_idx = _simulate_trade_return_with_exit(
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

            executed += 1
            returns.append(float(ret))
            active_until_idx = int(exit_idx)

    return _summarize_performance(
        returns=returns,
        considered_samples=considered,
        candidate_signals=candidates,
        executed_trades=executed,
        blocked_or_rejected=blocked,
    )


def _micro_entry_flags(
    close_price: float,
    ema_20: float,
    rsi: float,
    volume_spike: bool,
    side: int,
    pullback_tolerance: float,
) -> tuple[bool, bool, bool, bool]:
    if side == 1:
        pullback = close_price <= (ema_20 * (1.0 + pullback_tolerance))
        rsi_trigger = rsi < RSI_BUY_MAX
    else:
        pullback = close_price >= (ema_20 * (1.0 - pullback_tolerance))
        rsi_trigger = rsi > RSI_SELL_MIN

    volume_trigger = bool(volume_spike)
    accepted = bool(pullback or rsi_trigger or volume_trigger)
    return accepted, pullback, rsi_trigger, volume_trigger


def _backtest_micro_execution(
    frame_5m: pd.DataFrame,
    frame_1m: pd.DataFrame,
    pred_col: str,
    trade_col: str,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars_5m: int,
    entry_window_minutes: int,
    pullback_tolerance: float,
) -> tuple[dict[str, Any], pd.DataFrame]:
    returns: list[float] = []
    considered = 0
    candidates = 0
    executed = 0
    blocked = 0
    no_window_match = 0

    entry_records: list[dict[str, Any]] = []
    max_holding_1m = int(max_holding_bars_5m * 5)

    frame_1m_by_symbol: dict[str, pd.DataFrame] = {
        s: g.sort_values("timestamp").reset_index(drop=True)
        for s, g in frame_1m.groupby("symbol", sort=False)
    }

    for symbol, group_5m in frame_5m.groupby("symbol", sort=False):
        g5 = group_5m.sort_values("timestamp").reset_index(drop=True)
        if len(g5) < 2:
            continue

        g1 = frame_1m_by_symbol.get(str(symbol))
        if g1 is None or g1.empty:
            continue

        ts1 = g1["timestamp"].to_numpy(dtype="datetime64[ns]")
        close1 = g1["close"].to_numpy(dtype=np.float64)
        high1 = g1["high"].to_numpy(dtype=np.float64)
        low1 = g1["low"].to_numpy(dtype=np.float64)
        ema1 = g1["ema_20_entry"].to_numpy(dtype=np.float64)
        rsi1 = g1["rsi_entry"].to_numpy(dtype=np.float64)
        vol_spike1 = g1["volume_spike"].to_numpy(dtype=bool)

        ts5 = g5["timestamp"].to_numpy(dtype="datetime64[ns]")
        pred5 = g5[pred_col].to_numpy(dtype=np.int32)
        trade5 = g5[trade_col].to_numpy(dtype=bool)

        considered += int(len(g5) - 1)
        active_until_time = np.datetime64("1900-01-01")

        for i in range(len(g5) - 1):
            if not bool(trade5[i]):
                continue
            candidates += 1

            signal_time = ts5[i]
            if signal_time <= active_until_time:
                blocked += 1
                continue

            side = 1 if int(pred5[i]) == 1 else -1
            window_end = signal_time + np.timedelta64(int(entry_window_minutes), "m")

            start_idx = int(np.searchsorted(ts1, signal_time, side="right"))
            end_idx = int(np.searchsorted(ts1, window_end, side="right") - 1)
            if start_idx >= len(ts1) or start_idx > end_idx:
                no_window_match += 1
                continue

            selected_idx = -1
            selected_reason = ""
            for j in range(start_idx, min(end_idx + 1, len(ts1))):
                accepted, pullback, rsi_trigger, volume_trigger = _micro_entry_flags(
                    close_price=float(close1[j]),
                    ema_20=float(ema1[j]),
                    rsi=float(rsi1[j]),
                    volume_spike=bool(vol_spike1[j]),
                    side=side,
                    pullback_tolerance=pullback_tolerance,
                )
                if not accepted:
                    continue

                selected_idx = j
                if pullback:
                    selected_reason = "pullback_to_ema20"
                elif rsi_trigger:
                    selected_reason = "rsi_extreme"
                else:
                    selected_reason = "volume_spike"
                break

            if selected_idx < 0:
                no_window_match += 1
                continue

            ret, exit_idx = _simulate_trade_return_with_exit(
                close_arr=close1,
                high_arr=high1,
                low_arr=low1,
                entry_idx=selected_idx,
                side=side,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                max_holding_bars=max_holding_1m,
            )
            if ret is None:
                continue

            executed += 1
            returns.append(float(ret))
            active_until_time = ts1[int(exit_idx)]

            entry_records.append(
                {
                    "symbol": str(symbol),
                    "signal_time_5m": str(pd.Timestamp(signal_time)),
                    "entry_time_1m": str(pd.Timestamp(ts1[selected_idx])),
                    "exit_time_1m": str(pd.Timestamp(ts1[int(exit_idx)])),
                    "side": "BUY" if side == 1 else "SELL",
                    "entry_reason": selected_reason,
                    "entry_price": float(close1[selected_idx]),
                    "return": float(ret),
                }
            )

    stats = _summarize_performance(
        returns=returns,
        considered_samples=considered,
        candidate_signals=candidates,
        executed_trades=executed,
        blocked_or_rejected=(blocked + no_window_match),
    )
    stats["blocked_overlap"] = int(blocked)
    stats["micro_rejected_or_missing"] = int(no_window_match)
    stats["entry_window_minutes"] = int(entry_window_minutes)
    stats["max_holding_bars_1m"] = int(max_holding_1m)

    entries_df = pd.DataFrame(entry_records)
    return stats, entries_df


def run_backtest(
    dataset_path: Path,
    model_1h_path: Path,
    model_5m_path: Path,
    output_dir: Path,
    conf_1h_min: float,
    conf_5m_min: float,
    volume_spike_threshold: float,
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
    required = {"timestamp", "symbol", "timeframe", "close", "high", "low", "volume"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise RuntimeError(f"Dataset missing required columns: {missing}")

    frame_1h, X_1h = _prepare_model_frame(df, TIMEFRAME_1H, features_1h)
    frame_5m, X_5m = _prepare_model_frame(df, TIMEFRAME_5M, features_5m)

    split_5m = int(len(frame_5m) * 0.8)
    split_5m = max(1, min(len(frame_5m) - 1, split_5m))
    frame_5m_test = frame_5m.iloc[split_5m:].copy().reset_index(drop=True)
    X_5m_test = X_5m.iloc[split_5m:].copy().reset_index(drop=True)

    pred_1h, conf_1h, prob_1h = _predict_with_confidence(model_1h, X_1h)
    pred_5m, conf_5m, prob_5m = _predict_with_confidence(model_5m, X_5m_test)

    frame_1h_pred = frame_1h[["timestamp", "symbol"]].copy()
    frame_1h_pred["pred_1h"] = pred_1h
    frame_1h_pred["conf_1h"] = conf_1h
    frame_1h_pred["prob_buy_1h"] = prob_1h

    eval_5m = frame_5m_test[["timestamp", "symbol", "close", "high", "low"]].copy()
    eval_5m["pred_5m"] = pred_5m
    eval_5m["conf_5m"] = conf_5m
    eval_5m["prob_buy_5m"] = prob_5m

    eval_5m = _merge_asof_by_symbol(
        left=eval_5m,
        right=frame_1h_pred,
        right_columns=["pred_1h", "conf_1h", "prob_buy_1h"],
    )
    eval_5m = eval_5m.dropna(subset=["pred_1h", "conf_1h"]).copy().reset_index(drop=True)
    eval_5m["pred_1h"] = eval_5m["pred_1h"].astype(np.int32)

    eval_5m["trade_5m_only"] = eval_5m["conf_5m"] >= float(conf_5m_min)
    eval_5m["trade_1h_5m"] = (
        (eval_5m["conf_1h"] >= float(conf_1h_min))
        & (eval_5m["conf_5m"] >= float(conf_5m_min))
        & (eval_5m["pred_1h"] == eval_5m["pred_5m"])
    )

    test_start = pd.Timestamp(eval_5m["timestamp"].min())
    test_end = pd.Timestamp(eval_5m["timestamp"].max())
    extra_minutes = int(MICRO_ENTRY_WINDOW_MINUTES + MAX_HOLDING_BARS_1M)

    frame_1m_all = _prepare_micro_frame(df, volume_spike_threshold=volume_spike_threshold)
    frame_1m_eval = frame_1m_all[
        (frame_1m_all["timestamp"] >= test_start)
        & (frame_1m_all["timestamp"] <= test_end + pd.Timedelta(minutes=extra_minutes))
    ].copy()
    frame_1m_eval = frame_1m_eval.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if frame_1m_eval.empty:
        raise RuntimeError("No 1m rows available for evaluation window")

    stats_5m_only = _backtest_5m_execution(
        frame=eval_5m,
        pred_col="pred_5m",
        trade_col="trade_5m_only",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars=MAX_HOLDING_BARS_5M,
    )
    stats_1h_5m = _backtest_5m_execution(
        frame=eval_5m,
        pred_col="pred_5m",
        trade_col="trade_1h_5m",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars=MAX_HOLDING_BARS_5M,
    )
    stats_1h_5m_1m, micro_entries = _backtest_micro_execution(
        frame_5m=eval_5m,
        frame_1m=frame_1m_eval,
        pred_col="pred_5m",
        trade_col="trade_1h_5m",
        stop_loss_pct=STOP_LOSS_PCT,
        take_profit_pct=TAKE_PROFIT_PCT,
        max_holding_bars_5m=MAX_HOLDING_BARS_5M,
        entry_window_minutes=MICRO_ENTRY_WINDOW_MINUTES,
        pullback_tolerance=PULLBACK_TOLERANCE,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "mtf_1h_5m_1m_backtest_report.json"
    aligned_5m_path = output_dir / "mtf_1h_5m_1m_aligned_5m_predictions.csv"
    micro_entries_path = output_dir / "mtf_1h_5m_1m_micro_entries.csv"

    eval_5m.to_csv(aligned_5m_path, index=False)
    micro_entries.to_csv(micro_entries_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "models": {
            "model_1h": str(model_1h_path),
            "model_5m": str(model_5m_path),
        },
        "timeframes": {
            "trend": TIMEFRAME_1H,
            "signal": TIMEFRAME_5M,
            "micro_entry": TIMEFRAME_1M,
        },
        "evaluation_window": {
            "rows_5m_test": int(len(frame_5m_test)),
            "rows_5m_after_1h_alignment": int(len(eval_5m)),
            "rows_1m_eval": int(len(frame_1m_eval)),
            "start": str(test_start),
            "end": str(test_end),
        },
        "filters": {
            "confidence_1h_min": float(conf_1h_min),
            "confidence_5m_min": float(conf_5m_min),
            "trend_filter_rule": "trade only when 1h and 5m direction agree",
        },
        "micro_entry_rules": {
            "entry_window_minutes_after_5m_signal": MICRO_ENTRY_WINDOW_MINUTES,
            "pullback_rule": "BUY close <= EMA20(+tol), SELL close >= EMA20(-tol)",
            "pullback_tolerance": PULLBACK_TOLERANCE,
            "rsi_rule": "BUY RSI < 30 or SELL RSI > 70",
            "volume_spike_threshold": float(volume_spike_threshold),
            "entry_requires_any_of": [
                "pullback_to_ema20",
                "rsi_extreme",
                "volume_spike",
            ],
        },
        "execution": {
            "stop_loss_pct": STOP_LOSS_PCT,
            "take_profit_pct": TAKE_PROFIT_PCT,
            "max_holding_bars_5m": MAX_HOLDING_BARS_5M,
            "max_holding_bars_1m_for_micro": MAX_HOLDING_BARS_1M,
            "same_bar_policy": "conservative_stop_first",
        },
        "comparison": {
            "strategy_5m_only": stats_5m_only,
            "strategy_1h_plus_5m": stats_1h_5m,
            "strategy_1h_plus_5m_plus_1m": stats_1h_5m_1m,
        },
        "artifacts": {
            "report": str(report_path),
            "aligned_5m_predictions": str(aligned_5m_path),
            "micro_entries": str(micro_entries_path),
        },
    }

    report_path.write_text(json.dumps(_to_native(report), indent=2), encoding="utf-8")
    return _to_native(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest 5m-only, 1h+5m, and 1h+5m+1m micro-entry strategies"
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
        help="Path to 1h trend model payload",
    )
    parser.add_argument(
        "--model-5m",
        type=Path,
        default=Path("experiments_v2/outputs/models/5m_profit_model/xgb_5m_profit_model.joblib"),
        help="Path to 5m signal model payload",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments_v2/outputs/reports"),
        help="Output directory for reports",
    )
    parser.add_argument(
        "--conf-1h-min",
        type=float,
        default=CONF_1H_MIN,
        help="Minimum confidence for 1h trend model",
    )
    parser.add_argument(
        "--conf-5m-min",
        type=float,
        default=CONF_5M_MIN,
        help="Minimum confidence for 5m signal model",
    )
    parser.add_argument(
        "--volume-spike-threshold",
        type=float,
        default=VOLUME_SPIKE_THRESHOLD,
        help="Threshold for 1m volume spike rule",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_backtest(
        dataset_path=args.dataset,
        model_1h_path=args.model_1h,
        model_5m_path=args.model_5m,
        output_dir=args.output_dir,
        conf_1h_min=args.conf_1h_min,
        conf_5m_min=args.conf_5m_min,
        volume_spike_threshold=args.volume_spike_threshold,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
