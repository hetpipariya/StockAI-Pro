from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.metrics import (accuracy_score, classification_report,
                             confusion_matrix, f1_score, precision_score,
                             recall_score)
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.append(str(BACKEND_ROOT))

from app.inference.feature_engineering import (  # type: ignore
    UNIFIED_FEATURE_COLUMNS,
    compute_unified_features,
    validate_features,
)

LOGGER = logging.getLogger("experiments_v2.mtf")

IST_TIMEZONE = "Asia/Kolkata"
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)

TIMEFRAME_FREQ = {
    "1m": "1min",
    "5m": "5min",
    "1h": "1h",
}

LABEL_TO_CLASS = {-1: 0, 0: 1, 1: 2}
CLASS_TO_LABEL = {value: key for key, value in LABEL_TO_CLASS.items()}

CONTEXT_FEATURES_1H = [
    "ema21",
    "ema50",
    "rsi14",
    "macd_hist",
    "atr14",
    "adx14",
    "daily_alignment",
    "nifty_direction",
]


@dataclass
class LoadConfig:
    data_dir: Path
    timeframe: str
    max_files: int | None = None
    fill_gaps: bool = True
    drop_gap_filled: bool = True
    min_rows_per_symbol: int = 200


@dataclass
class LabelConfig:
    take_profit_pct: float = 0.005
    stop_loss_pct: float = 0.0035
    max_holding_bars: int = 12
    neutral_band_pct: float = 0.0015


@dataclass
class TrainConfig:
    train_fraction: float = 0.70
    valid_fraction: float = 0.15
    random_state: int = 42
    n_estimators: int = 500
    max_depth: int = 6
    learning_rate: float = 0.05
    subsample: float = 0.9
    colsample_bytree: float = 0.9
    calibration_method: str = "isotonic"


@dataclass
class EvalConfig:
    confidence_threshold: float = 0.60
    slippage_bps: float = 5.0


def setup_logging(level: str = "INFO") -> None:
    if logging.getLogger().handlers:
        return
    logging.basicConfig(
        level=getattr(logging, str(level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s %(message)s",
    )


def _normalize_timestamp(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce")
    if parsed.dt.tz is None:
        return parsed.dt.tz_localize(IST_TIMEZONE, nonexistent="shift_forward", ambiguous="NaT").dt.tz_localize(None)
    return parsed.dt.tz_convert(IST_TIMEZONE).dt.tz_localize(None)


def _normalize_columns(frame: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in frame.columns:
        key = str(col).strip().lower()
        if key in {"timestamp", "datetime", "date", "time"}:
            rename_map[col] = "timestamp"
        elif key in {"symbol", "ticker"}:
            rename_map[col] = "symbol"
        elif key in {"timeframe", "tf", "interval"}:
            rename_map[col] = "timeframe"
        elif key in {"open", "high", "low", "close", "volume"}:
            rename_map[col] = key
    return frame.rename(columns=rename_map)


def _infer_symbol_from_path(path: Path) -> str:
    token = path.stem.upper()
    token = token.replace("-", "_")
    token = token.replace(".NS", "")
    token = token.replace("_RAW", "")
    token = token.replace("_PROCESSED", "")
    token = token.replace("_5M", "")
    token = token.replace("_1M", "")
    token = token.replace("_1H", "")
    return token.strip() or "UNKNOWN"


def _filter_market_hours(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out = out[out["timestamp"].dt.dayofweek < 5]
    in_session = (out["timestamp"].dt.time >= MARKET_OPEN) & (out["timestamp"].dt.time <= MARKET_CLOSE)
    return out[in_session].copy()


def _expected_index_for_day(day: pd.Timestamp, timeframe: str) -> pd.DatetimeIndex:
    freq = TIMEFRAME_FREQ.get(timeframe, "5min")
    start = pd.Timestamp.combine(day, MARKET_OPEN)
    end = pd.Timestamp.combine(day, MARKET_CLOSE)
    return pd.date_range(start=start, end=end, freq=freq)


def _reindex_symbol_session(group: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if group.empty:
        return group.copy()

    g = group.sort_values("timestamp").copy()
    g = g.set_index("timestamp")

    days = g.index.normalize().unique().sort_values()
    if len(days) == 0:
        return g.reset_index()

    full_index = None
    for day in days:
        idx = _expected_index_for_day(day, timeframe)
        full_index = idx if full_index is None else full_index.union(idx)

    if full_index is None:
        return g.reset_index()

    expanded = g.reindex(full_index)
    gap_mask = expanded[["open", "high", "low", "close", "volume"]].isna().all(axis=1)
    expanded["is_gap_filled"] = gap_mask.astype(int)

    prior_close = expanded["close"].ffill()
    expanded = expanded[prior_close.notna()].copy()
    prior_close = prior_close.loc[expanded.index]

    for col in ["open", "high", "low", "close"]:
        expanded[col] = pd.to_numeric(expanded[col], errors="coerce").fillna(prior_close)

    expanded["volume"] = pd.to_numeric(expanded["volume"], errors="coerce").fillna(0.0)
    expanded.loc[expanded["volume"] < 0, "volume"] = 0.0

    row_max = expanded[["open", "high", "low", "close"]].max(axis=1)
    row_min = expanded[["open", "high", "low", "close"]].min(axis=1)
    expanded["high"] = row_max
    expanded["low"] = row_min

    expanded.index.name = "timestamp"
    out = expanded.reset_index()
    return out


def _load_csv_files(config: LoadConfig) -> pd.DataFrame:
    if not config.data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {config.data_dir}")

    files = sorted(config.data_dir.glob("*.csv"))
    if config.max_files:
        files = files[: int(config.max_files)]
    if not files:
        raise FileNotFoundError(f"No CSV files found in {config.data_dir}")

    frames: list[pd.DataFrame] = []
    for path in files:
        frame = pd.read_csv(path, low_memory=False)
        frame = _normalize_columns(frame)

        if "timestamp" not in frame.columns:
            continue

        if "symbol" not in frame.columns:
            frame["symbol"] = _infer_symbol_from_path(path)

        frame["timestamp"] = _normalize_timestamp(frame["timestamp"])
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["timeframe"] = str(config.timeframe).lower()

        required = ["open", "high", "low", "close", "volume"]
        for col in required:
            if col not in frame.columns:
                frame[col] = np.nan
            frame[col] = pd.to_numeric(frame[col], errors="coerce")

        frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"]).copy()
        frame = _filter_market_hours(frame)
        frame = frame.sort_values(["symbol", "timestamp"]).drop_duplicates(
            subset=["symbol", "timestamp"], keep="last"
        )
        frames.append(frame)

    if not frames:
        raise RuntimeError(f"No valid OHLCV rows found in {config.data_dir}")

    merged = pd.concat(frames, ignore_index=True)
    return merged.reset_index(drop=True)


def load_and_clean_ohlcv(config: LoadConfig) -> pd.DataFrame:
    raw = _load_csv_files(config)
    blocks: list[pd.DataFrame] = []

    for symbol, group in raw.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").copy()
        if config.fill_gaps:
            g = _reindex_symbol_session(g, config.timeframe)
        else:
            g["is_gap_filled"] = 0

        if config.drop_gap_filled:
            g = g[g["is_gap_filled"] == 0].copy()

        if len(g) < int(config.min_rows_per_symbol):
            continue

        blocks.append(g)

    if not blocks:
        raise RuntimeError("No symbols left after cleaning and gap handling.")

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


def build_feature_frame(ohlcv_df: pd.DataFrame) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    for symbol, group in ohlcv_df.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True)
        raw = g[["open", "high", "low", "close", "volume"]].copy()

        features = compute_unified_features(raw, strict=True)
        if features.empty:
            continue

        aligned = g.tail(len(features)).reset_index(drop=True)
        block = pd.concat(
            [
                aligned[["timestamp", "symbol", "timeframe", "open", "high", "low", "close", "volume"]],
                features.reset_index(drop=True),
            ],
            axis=1,
        )
        blocks.append(block)

    if not blocks:
        return pd.DataFrame()

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    validate_features(list(out.columns[out.columns.isin(UNIFIED_FEATURE_COLUMNS)]), expected=list(UNIFIED_FEATURE_COLUMNS), context="training")
    return out


def merge_context_1h(base_5m: pd.DataFrame, frame_1h: pd.DataFrame) -> pd.DataFrame:
    missing = [col for col in CONTEXT_FEATURES_1H if col not in frame_1h.columns]
    if missing:
        raise RuntimeError(f"1h context missing features: {missing}")

    ctx = frame_1h[["timestamp", "symbol", *CONTEXT_FEATURES_1H]].copy()
    rename_map = {col: f"{col}_1h" for col in CONTEXT_FEATURES_1H}
    ctx = ctx.rename(columns=rename_map)

    merged_parts: list[pd.DataFrame] = []
    for symbol, group in base_5m.groupby("symbol", sort=False):
        left = group.sort_values("timestamp").copy()
        right = ctx[ctx["symbol"] == symbol].sort_values("timestamp").copy()
        if right.empty:
            raise RuntimeError(f"No 1h context rows for symbol: {symbol}")

        merged = pd.merge_asof(
            left,
            right.drop(columns=["symbol"]),
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
        merged["symbol"] = symbol
        merged_parts.append(merged)

    out = pd.concat(merged_parts, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    return out


def build_labels(
    frame: pd.DataFrame,
    config: LabelConfig,
) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    for symbol, group in frame.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True).copy()
        close = g["close"].to_numpy(dtype=np.float64)
        high = g["high"].to_numpy(dtype=np.float64)
        low = g["low"].to_numpy(dtype=np.float64)

        labels = np.zeros(len(g), dtype=np.int32)

        for idx in range(len(g) - 1):
            entry = float(close[idx])
            if not np.isfinite(entry) or entry <= 0:
                continue

            up_target = entry * (1.0 + float(config.take_profit_pct))
            down_target = entry * (1.0 - float(config.take_profit_pct))
            up_stop = entry * (1.0 + float(config.stop_loss_pct))
            down_stop = entry * (1.0 - float(config.stop_loss_pct))

            end_idx = min(len(g) - 1, idx + int(config.max_holding_bars))
            label = 0
            event = "time"

            for j in range(idx + 1, end_idx + 1):
                bar_high = float(high[j])
                bar_low = float(low[j])

                hit_buy_tp = bar_high >= up_target
                hit_buy_sl = bar_low <= down_stop
                hit_sell_tp = bar_low <= down_target
                hit_sell_sl = bar_high >= up_stop

                if hit_buy_tp and hit_sell_tp:
                    close_j = float(close[j])
                    label = 1 if close_j >= entry else -1
                    event = "both_tp_same_bar"
                    break
                if hit_buy_tp:
                    label = 1
                    event = "buy_tp"
                    break
                if hit_sell_tp:
                    label = -1
                    event = "sell_tp"
                    break

                if hit_buy_sl and hit_sell_sl:
                    label = 0
                    event = "both_sl_same_bar"
                    break

            if event == "time":
                exit_close = float(close[end_idx])
                ret = (exit_close - entry) / max(entry, 1e-9)
                if ret > float(config.neutral_band_pct):
                    label = 1
                elif ret < -float(config.neutral_band_pct):
                    label = -1
                else:
                    label = 0

            labels[idx] = int(label)

        g["target_class"] = labels
        blocks.append(g)

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    out = out[out["target_class"].isin([-1, 0, 1])].copy()
    return out


def time_split(frame: pd.DataFrame, train_fraction: float, valid_fraction: float) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if frame.empty:
        raise RuntimeError("Empty dataset for split")

    ordered = frame.sort_values("timestamp").reset_index(drop=True)
    n = len(ordered)
    train_end = int(n * float(train_fraction))
    valid_end = int(n * float(train_fraction + valid_fraction))

    train_df = ordered.iloc[: max(1, train_end)].copy()
    valid_df = ordered.iloc[train_end: max(train_end + 1, valid_end)].copy()
    test_df = ordered.iloc[valid_end:].copy()

    return train_df, valid_df, test_df


def build_feature_matrix(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    missing = [col for col in feature_columns if col not in frame.columns]
    if missing:
        raise RuntimeError(f"Missing feature columns: {missing}")

    X = frame[feature_columns].astype(float)
    X = X.replace([np.inf, -np.inf], np.nan)
    if X.isna().any(axis=None):
        raise RuntimeError("NaN detected in feature matrix. Check cleaning and rolling windows.")
    return X


def compute_class_weights(y: np.ndarray) -> np.ndarray:
    counts = np.bincount(y, minlength=3).astype(float)
    counts[counts == 0] = 1.0
    total = counts.sum()
    weights = total / (len(counts) * counts)
    return np.array([weights[label] for label in y], dtype=np.float32)


def train_model(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_columns: list[str],
    config: TrainConfig,
) -> tuple[Any, Any, dict[str, Any]]:
    X_train = build_feature_matrix(train_df, feature_columns)
    X_valid = build_feature_matrix(valid_df, feature_columns)

    y_train = train_df["target_class"].map(LABEL_TO_CLASS).astype(int).to_numpy()
    y_valid = valid_df["target_class"].map(LABEL_TO_CLASS).astype(int).to_numpy()

    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_valid_scaled = scaler.transform(X_valid)

    sample_weight = compute_class_weights(y_train)

    model = XGBClassifier(
        objective="multi:softprob",
        num_class=3,
        eval_metric="mlogloss",
        n_estimators=int(config.n_estimators),
        max_depth=int(config.max_depth),
        learning_rate=float(config.learning_rate),
        subsample=float(config.subsample),
        colsample_bytree=float(config.colsample_bytree),
        random_state=int(config.random_state),
        n_jobs=-1,
        tree_method="hist",
    )
    model.fit(X_train_scaled, y_train, sample_weight=sample_weight)

    calibration_method = str(config.calibration_method).lower()
    if calibration_method not in {"sigmoid", "isotonic"}:
        calibration_method = "sigmoid"

    calibrator = CalibratedClassifierCV(model, method=calibration_method, cv="prefit")
    calibrator.fit(X_valid_scaled, y_valid)

    meta = {
        "calibration_method": calibration_method,
        "train_rows": int(len(train_df)),
        "valid_rows": int(len(valid_df)),
        "class_distribution": {
            "SELL": int(np.sum(y_train == 0)),
            "HOLD": int(np.sum(y_train == 1)),
            "BUY": int(np.sum(y_train == 2)),
        },
    }

    return model, calibrator, meta


def predict_with_calibration(
    model: Any,
    calibrator: Any,
    scaler: StandardScaler,
    frame: pd.DataFrame,
    feature_columns: list[str],
) -> pd.DataFrame:
    X = build_feature_matrix(frame, feature_columns)
    X_scaled = scaler.transform(X)

    raw_proba = model.predict_proba(X_scaled)
    cal_proba = calibrator.predict_proba(X_scaled)

    raw_pred = np.argmax(raw_proba, axis=1)
    cal_pred = np.argmax(cal_proba, axis=1)

    out = frame.copy().reset_index(drop=True)
    out["pred_raw"] = [CLASS_TO_LABEL[int(v)] for v in raw_pred]
    out["pred"] = [CLASS_TO_LABEL[int(v)] for v in cal_pred]
    out["confidence"] = np.max(cal_proba, axis=1)
    out["prob_sell"] = cal_proba[:, 0]
    out["prob_hold"] = cal_proba[:, 1]
    out["prob_buy"] = cal_proba[:, 2]
    return out


def evaluate_classification(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, Any]:
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "precision_macro": float(precision_score(y_true, y_pred, average="macro", zero_division=0)),
        "recall_macro": float(recall_score(y_true, y_pred, average="macro", zero_division=0)),
        "f1_macro": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[-1, 0, 1]).tolist(),
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=[-1, 0, 1],
            target_names=["SELL", "HOLD", "BUY"],
            output_dict=True,
            zero_division=0,
        ),
    }


def calibration_diagnostics(y_true: np.ndarray, prob_buy: np.ndarray, prob_sell: np.ndarray) -> dict[str, Any]:
    buy_true = (y_true == 1).astype(int)
    sell_true = (y_true == -1).astype(int)

    buy_frac, buy_mean = calibration_curve(buy_true, prob_buy, n_bins=10)
    sell_frac, sell_mean = calibration_curve(sell_true, prob_sell, n_bins=10)

    return {
        "buy": {
            "prob_mean": buy_mean.tolist(),
            "frac_positive": buy_frac.tolist(),
        },
        "sell": {
            "prob_mean": sell_mean.tolist(),
            "frac_positive": sell_frac.tolist(),
        },
    }


def apply_signal_filters(
    frame: pd.DataFrame,
    confidence_threshold: float,
    volume_threshold: float,
    volatility_threshold: float,
) -> pd.DataFrame:
    out = frame.copy()
    out["trade_allowed"] = True
    out.loc[out["confidence"] < float(confidence_threshold), "trade_allowed"] = False
    out.loc[out["volume_ratio"] < float(volume_threshold), "trade_allowed"] = False
    out.loc[out["volatility"] < float(volatility_threshold), "trade_allowed"] = False
    return out


def simulate_trades(
    frame: pd.DataFrame,
    label_config: LabelConfig,
    eval_config: EvalConfig,
    trend_filter_col: str | None = None,
) -> dict[str, Any]:
    work = frame.copy().reset_index(drop=True)
    if trend_filter_col and trend_filter_col in work.columns:
        work = work[work[trend_filter_col].notna()].copy()

    entry_slippage = float(eval_config.slippage_bps) / 10_000.0
    exit_slippage = float(eval_config.slippage_bps) / 10_000.0

    trades: list[float] = []
    total_signals = 0

    for symbol, group in work.groupby("symbol", sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True)
        close = g["close"].to_numpy(dtype=np.float64)
        high = g["high"].to_numpy(dtype=np.float64)
        low = g["low"].to_numpy(dtype=np.float64)
        pred = g["pred"].to_numpy(dtype=np.int32)
        allowed = g["trade_allowed"].to_numpy(dtype=bool)

        active_until = -1
        for i in range(len(g) - 1):
            if not allowed[i] or pred[i] == 0:
                continue

            total_signals += 1
            if i <= active_until:
                continue

            side = int(pred[i])
            entry = float(close[i])
            if not np.isfinite(entry) or entry <= 0:
                continue

            entry_price = entry * (1.0 + entry_slippage) if side == 1 else entry * (1.0 - entry_slippage)

            tp = entry_price * (1.0 + label_config.take_profit_pct) if side == 1 else entry_price * (1.0 - label_config.take_profit_pct)
            sl = entry_price * (1.0 - label_config.stop_loss_pct) if side == 1 else entry_price * (1.0 + label_config.stop_loss_pct)

            end_idx = min(len(g) - 1, i + int(label_config.max_holding_bars))
            exit_price = None

            for j in range(i + 1, end_idx + 1):
                bar_high = float(high[j])
                bar_low = float(low[j])

                if side == 1:
                    hit_tp = bar_high >= tp
                    hit_sl = bar_low <= sl
                    if hit_tp and hit_sl:
                        exit_price = sl
                        active_until = j
                        break
                    if hit_sl:
                        exit_price = sl
                        active_until = j
                        break
                    if hit_tp:
                        exit_price = tp
                        active_until = j
                        break
                else:
                    hit_tp = bar_low <= tp
                    hit_sl = bar_high >= sl
                    if hit_tp and hit_sl:
                        exit_price = sl
                        active_until = j
                        break
                    if hit_sl:
                        exit_price = sl
                        active_until = j
                        break
                    if hit_tp:
                        exit_price = tp
                        active_until = j
                        break

            if exit_price is None:
                exit_price = float(close[end_idx])
                active_until = end_idx

            exit_price = exit_price * (1.0 - exit_slippage) if side == 1 else exit_price * (1.0 + exit_slippage)
            pnl = (exit_price - entry_price) / entry_price if side == 1 else (entry_price - exit_price) / entry_price
            trades.append(float(pnl))

    if not trades:
        return {
            "total_trades": 0,
            "profit_factor": None,
            "win_rate": 0.0,
            "avg_return": 0.0,
            "total_signals": int(total_signals),
        }

    returns = np.asarray(trades, dtype=np.float64)
    wins = np.sum(returns > 0)
    gross_profit = float(returns[returns > 0].sum())
    gross_loss = float(abs(returns[returns < 0].sum()))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else None

    return {
        "total_trades": int(len(returns)),
        "profit_factor": profit_factor,
        "win_rate": float(wins / max(len(returns), 1)),
        "avg_return": float(np.mean(returns)),
        "total_signals": int(total_signals),
    }


def save_artifacts(
    output_dir: Path,
    model: Any,
    calibrator: Any,
    scaler: StandardScaler,
    feature_columns: list[str],
    metadata: dict[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)

    model_path = output_dir / "model.pkl"
    calibrator_path = output_dir / "calibrator.pkl"
    scaler_path = output_dir / "scaler.pkl"
    feature_path = output_dir / "feature_list.json"
    meta_path = output_dir / "training_metadata.json"

    joblib.dump(model, model_path)
    joblib.dump(calibrator, calibrator_path)
    joblib.dump(scaler, scaler_path)
    feature_path.write_text(json.dumps(feature_columns, indent=2), encoding="utf-8")
    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    return {
        "model": str(model_path),
        "calibrator": str(calibrator_path),
        "scaler": str(scaler_path),
        "feature_list": str(feature_path),
        "metadata": str(meta_path),
    }
