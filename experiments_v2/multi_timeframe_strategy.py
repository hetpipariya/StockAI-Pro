from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd


EPSILON = 1e-9


@dataclass
class StrategyConfig:
    ema_fast: int = 12
    ema_slow: int = 26
    ema_trend: int = 50
    rsi_period: int = 14
    macd_signal_span: int = 9
    volume_lookback: int = 20

    bullish_rsi_floor: float = 52.0
    bearish_rsi_ceiling: float = 48.0
    confirmation_volume_ratio: float = 1.10

    hourly_trend_min_strength: float = 0.0015
    min_signal_confidence: float = 0.55


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _safe_numeric(series: pd.Series) -> pd.Series:
    out = pd.to_numeric(series, errors="coerce")
    return out.replace([np.inf, -np.inf], np.nan)


def _compute_rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / max(period, 1), adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / max(period, 1), adjust=False).mean()
    rs = avg_gain / (avg_loss + EPSILON)
    return 100.0 - (100.0 / (1.0 + rs))


def add_indicators(frame: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    out = frame.copy()
    out["close"] = _safe_numeric(out["close"])
    out["volume"] = _safe_numeric(out["volume"])

    close = out["close"]

    out["ema_fast"] = close.ewm(span=config.ema_fast, adjust=False).mean()
    out["ema_slow"] = close.ewm(span=config.ema_slow, adjust=False).mean()
    out["ema_trend"] = close.ewm(span=config.ema_trend, adjust=False).mean()

    out["rsi"] = _compute_rsi(close=close, period=config.rsi_period)

    out["macd"] = out["ema_fast"] - out["ema_slow"]
    out["macd_signal"] = out["macd"].ewm(span=config.macd_signal_span, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    volume_ma = out["volume"].rolling(config.volume_lookback, min_periods=5).mean()
    out["volume_ratio"] = out["volume"] / (volume_ma + EPSILON)

    out["ema_spread"] = (out["ema_fast"] - out["ema_slow"]) / (close.abs() + EPSILON)
    out["trend_distance"] = (close - out["ema_trend"]) / (close.abs() + EPSILON)
    return out


def classify_hourly_trend(frame_1h: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    out = add_indicators(frame_1h, config=config)

    bullish = (
        (out["ema_fast"] > out["ema_slow"])
        & (out["close"] >= out["ema_trend"])
        & (out["rsi"] >= config.bullish_rsi_floor)
        & (out["macd"] > out["macd_signal"])
        & (out["ema_spread"] >= config.hourly_trend_min_strength)
    )
    bearish = (
        (out["ema_fast"] < out["ema_slow"])
        & (out["close"] <= out["ema_trend"])
        & (out["rsi"] <= config.bearish_rsi_ceiling)
        & (out["macd"] < out["macd_signal"])
        & (out["ema_spread"] <= -config.hourly_trend_min_strength)
    )

    out["trend"] = np.where(bullish, "BULLISH", np.where(bearish, "BEARISH", "SIDEWAYS"))

    trend_strength_raw = (
        (out["ema_spread"].abs() * 150.0)
        + (out["trend_distance"].abs() * 80.0)
        + ((out["rsi"] - 50.0).abs() / 50.0)
    ) / 3.0
    out["trend_strength"] = np.clip(trend_strength_raw, 0.0, 1.0)
    return out


def build_5m_entry_setups(frame_5m: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    out = add_indicators(frame_5m, config=config)

    macd_cross_up = (out["macd"] > out["macd_signal"]) & (out["macd"].shift(1) <= out["macd_signal"].shift(1))
    macd_cross_down = (out["macd"] < out["macd_signal"]) & (out["macd"].shift(1) >= out["macd_signal"].shift(1))

    buy_setup = (
        (out["ema_fast"] > out["ema_slow"])
        & (out["rsi"] >= 50.0)
        & (out["macd_hist"] > 0.0)
        & (macd_cross_up | (out["macd_hist"] > out["macd_hist"].shift(1)))
    )
    sell_setup = (
        (out["ema_fast"] < out["ema_slow"])
        & (out["rsi"] <= 50.0)
        & (out["macd_hist"] < 0.0)
        & (macd_cross_down | (out["macd_hist"] < out["macd_hist"].shift(1)))
    )

    out["setup_buy_5m"] = buy_setup.astype(int)
    out["setup_sell_5m"] = sell_setup.astype(int)
    out["volume_confirm_5m"] = (out["volume_ratio"] >= config.confirmation_volume_ratio).astype(int)

    out["entry_score_buy_5m"] = np.clip(
        0.35 * (out["ema_spread"].clip(lower=0.0) * 200.0)
        + 0.25 * ((out["rsi"] - 50.0).clip(lower=0.0) / 25.0)
        + 0.25 * (out["macd_hist"].clip(lower=0.0) * 50.0)
        + 0.15 * out["volume_confirm_5m"],
        0.0,
        1.0,
    )
    out["entry_score_sell_5m"] = np.clip(
        0.35 * ((-out["ema_spread"]).clip(lower=0.0) * 200.0)
        + 0.25 * ((50.0 - out["rsi"]).clip(lower=0.0) / 25.0)
        + 0.25 * ((-out["macd_hist"]).clip(lower=0.0) * 50.0)
        + 0.15 * out["volume_confirm_5m"],
        0.0,
        1.0,
    )
    return out


def build_1m_timing(frame_1m: pd.DataFrame, config: StrategyConfig) -> pd.DataFrame:
    out = add_indicators(frame_1m, config=config)

    high = _safe_numeric(out["high"])
    low = _safe_numeric(out["low"])

    break_up = out["close"] > high.shift(1).rolling(3, min_periods=2).max()
    break_down = out["close"] < low.shift(1).rolling(3, min_periods=2).min()

    buy_confirm = (
        (out["ema_fast"] > out["ema_slow"])
        & (out["rsi"] > 50.0)
        & (out["macd_hist"] > 0.0)
        & break_up
        & (out["volume_ratio"] >= config.confirmation_volume_ratio)
    )
    sell_confirm = (
        (out["ema_fast"] < out["ema_slow"])
        & (out["rsi"] < 50.0)
        & (out["macd_hist"] < 0.0)
        & break_down
        & (out["volume_ratio"] >= config.confirmation_volume_ratio)
    )

    out["confirm_buy_1m"] = buy_confirm.astype(int)
    out["confirm_sell_1m"] = sell_confirm.astype(int)

    out["timing_score_buy_1m"] = np.clip(
        0.40 * (out["ema_spread"].clip(lower=0.0) * 220.0)
        + 0.25 * ((out["rsi"] - 50.0).clip(lower=0.0) / 20.0)
        + 0.20 * (out["macd_hist"].clip(lower=0.0) * 60.0)
        + 0.15 * (out["volume_ratio"] >= config.confirmation_volume_ratio).astype(float),
        0.0,
        1.0,
    )
    out["timing_score_sell_1m"] = np.clip(
        0.40 * ((-out["ema_spread"]).clip(lower=0.0) * 220.0)
        + 0.25 * ((50.0 - out["rsi"]).clip(lower=0.0) / 20.0)
        + 0.20 * ((-out["macd_hist"]).clip(lower=0.0) * 60.0)
        + 0.15 * (out["volume_ratio"] >= config.confirmation_volume_ratio).astype(float),
        0.0,
        1.0,
    )
    return out


def _merge_asof_by_symbol(
    base: pd.DataFrame,
    right: pd.DataFrame,
    right_columns: list[str],
) -> pd.DataFrame:
    merged_parts: list[pd.DataFrame] = []

    symbols = sorted(set(base["symbol"].astype(str).unique().tolist()))
    for symbol in symbols:
        left_symbol = base[base["symbol"].astype(str) == symbol].copy()
        right_symbol = right[right["symbol"].astype(str) == symbol].copy()

        left_symbol = left_symbol.sort_values("timestamp")
        right_symbol = right_symbol.sort_values("timestamp")

        if right_symbol.empty:
            for col in right_columns:
                left_symbol[col] = np.nan
            merged_parts.append(left_symbol)
            continue

        merged = pd.merge_asof(
            left_symbol,
            right_symbol[["timestamp"] + right_columns],
            on="timestamp",
            direction="backward",
            allow_exact_matches=True,
        )
        merged_parts.append(merged)

    if not merged_parts:
        return base.copy()

    out = pd.concat(merged_parts, ignore_index=True)
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def generate_multi_timeframe_signals(
    frame_1m: pd.DataFrame,
    frame_5m: pd.DataFrame,
    frame_1h: pd.DataFrame,
    config: StrategyConfig | None = None,
) -> pd.DataFrame:
    if config is None:
        config = StrategyConfig()

    required = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    for name, frame in (("1m", frame_1m), ("5m", frame_5m), ("1h", frame_1h)):
        missing = [col for col in required if col not in frame.columns]
        if missing:
            raise ValueError(f"{name} data is missing required columns: {missing}")

    one_m = frame_1m.copy()
    five_m = frame_5m.copy()
    one_h = frame_1h.copy()

    for frame in (one_m, five_m, one_h):
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame["symbol"] = frame["symbol"].astype(str)

    one_m = one_m.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    five_m = five_m.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    one_h = one_h.dropna(subset=["timestamp"]).sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    one_h_state = classify_hourly_trend(frame_1h=one_h, config=config)
    one_h_state = one_h_state[["timestamp", "symbol", "trend", "trend_strength"]]

    five_m_state = build_5m_entry_setups(frame_5m=five_m, config=config)
    five_m_state = five_m_state[
        [
            "timestamp",
            "symbol",
            "setup_buy_5m",
            "setup_sell_5m",
            "entry_score_buy_5m",
            "entry_score_sell_5m",
            "volume_confirm_5m",
        ]
    ]

    one_m_state = build_1m_timing(frame_1m=one_m, config=config)
    one_m_state = one_m_state[
        [
            "timestamp",
            "symbol",
            "confirm_buy_1m",
            "confirm_sell_1m",
            "timing_score_buy_1m",
            "timing_score_sell_1m",
            "volume_ratio",
        ]
    ]

    merged = _merge_asof_by_symbol(
        base=one_m_state,
        right=five_m_state,
        right_columns=[
            "setup_buy_5m",
            "setup_sell_5m",
            "entry_score_buy_5m",
            "entry_score_sell_5m",
            "volume_confirm_5m",
        ],
    )
    merged = _merge_asof_by_symbol(
        base=merged,
        right=one_h_state,
        right_columns=["trend", "trend_strength"],
    )

    merged["trend"] = merged["trend"].fillna("SIDEWAYS")
    merged["trend_strength"] = _safe_numeric(merged["trend_strength"]).fillna(0.0)

    for col in [
        "setup_buy_5m",
        "setup_sell_5m",
        "confirm_buy_1m",
        "confirm_sell_1m",
        "volume_confirm_5m",
    ]:
        merged[col] = _safe_numeric(merged[col]).fillna(0.0).astype(int)

    for col in [
        "entry_score_buy_5m",
        "entry_score_sell_5m",
        "timing_score_buy_1m",
        "timing_score_sell_1m",
        "volume_ratio",
    ]:
        merged[col] = _safe_numeric(merged[col]).fillna(0.0)

    signals: list[str] = []
    confidences: list[float] = []
    reasons: list[str] = []

    for row in merged.itertuples(index=False):
        trend = str(getattr(row, "trend", "SIDEWAYS"))
        trend_strength = float(getattr(row, "trend_strength", 0.0) or 0.0)

        setup_buy = int(getattr(row, "setup_buy_5m", 0) or 0)
        setup_sell = int(getattr(row, "setup_sell_5m", 0) or 0)
        confirm_buy = int(getattr(row, "confirm_buy_1m", 0) or 0)
        confirm_sell = int(getattr(row, "confirm_sell_1m", 0) or 0)

        entry_score_buy = float(getattr(row, "entry_score_buy_5m", 0.0) or 0.0)
        entry_score_sell = float(getattr(row, "entry_score_sell_5m", 0.0) or 0.0)
        timing_score_buy = float(getattr(row, "timing_score_buy_1m", 0.0) or 0.0)
        timing_score_sell = float(getattr(row, "timing_score_sell_1m", 0.0) or 0.0)

        volume_confirm_5m = int(getattr(row, "volume_confirm_5m", 0) or 0)
        volume_ratio_1m = float(getattr(row, "volume_ratio", 0.0) or 0.0)
        volume_confirm_1m = 1 if volume_ratio_1m >= config.confirmation_volume_ratio else 0

        if trend == "BULLISH":
            raw_conf = (
                0.45 * _clip01(trend_strength)
                + 0.35 * _clip01(entry_score_buy)
                + 0.20 * _clip01(timing_score_buy)
            )
            if setup_buy and confirm_buy:
                volume_bonus = 0.03 * (volume_confirm_5m + volume_confirm_1m)
                conf = _clip01(raw_conf + volume_bonus)
                if conf >= config.min_signal_confidence:
                    signal = "BUY"
                    reason = "1h bullish, 5m buy setup, 1m buy confirmation"
                else:
                    signal = "HOLD"
                    reason = "Bullish alignment but confidence below threshold"
            else:
                signal = "HOLD"
                conf = _clip01(raw_conf * 0.85)
                reason = "1h bullish but 5m/1m entry not fully aligned"
        elif trend == "BEARISH":
            raw_conf = (
                0.45 * _clip01(trend_strength)
                + 0.35 * _clip01(entry_score_sell)
                + 0.20 * _clip01(timing_score_sell)
            )
            if setup_sell and confirm_sell:
                volume_bonus = 0.03 * (volume_confirm_5m + volume_confirm_1m)
                conf = _clip01(raw_conf + volume_bonus)
                if conf >= config.min_signal_confidence:
                    signal = "SELL"
                    reason = "1h bearish, 5m sell setup, 1m sell confirmation"
                else:
                    signal = "HOLD"
                    reason = "Bearish alignment but confidence below threshold"
            else:
                signal = "HOLD"
                conf = _clip01(raw_conf * 0.85)
                reason = "1h bearish but 5m/1m entry not fully aligned"
        else:
            signal = "HOLD"
            conf = _clip01(0.15 + (0.35 * _clip01(trend_strength)))
            reason = "1h trend sideways, strategy gated to HOLD"

        signals.append(signal)
        confidences.append(conf)
        reasons.append(reason)

    merged["signal"] = signals
    merged["confidence"] = np.round(confidences, 4)
    merged["reason"] = reasons

    return merged[
        [
            "timestamp",
            "symbol",
            "trend",
            "trend_strength",
            "setup_buy_5m",
            "setup_sell_5m",
            "confirm_buy_1m",
            "confirm_sell_1m",
            "signal",
            "confidence",
            "reason",
        ]
    ]


def example_signal_flow() -> dict[str, object]:
    return {
        "flow": [
            "1h trend: EMA12>EMA26, RSI>52, MACD>signal -> BULLISH",
            "5m setup: bullish EMA spread + MACD histogram rising + volume ratio>1.1",
            "1m trigger: breakout of recent 3-bar high + MACD histogram positive + volume confirm",
            "final decision: BUY if confidence >= min threshold, else HOLD",
        ],
        "notes": [
            "If 1h trend is SIDEWAYS, force HOLD.",
            "If 1h trend is BULLISH, suppress SELL candidates.",
            "If 1h trend is BEARISH, suppress BUY candidates.",
        ],
    }


def _read_ohlcv_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    required = ["timestamp", "symbol", "open", "high", "low", "close", "volume"]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise ValueError(f"{path} missing required columns: {missing}")
    return df[required].copy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Multi-timeframe strategy pipeline (1h/5m/1m)")
    parser.add_argument("--data-1m", type=Path, help="CSV path for 1m OHLCV")
    parser.add_argument("--data-5m", type=Path, help="CSV path for 5m OHLCV")
    parser.add_argument("--data-1h", type=Path, help="CSV path for 1h OHLCV")
    parser.add_argument("--out", type=Path, default=None, help="Optional output CSV path")
    parser.add_argument("--print-example-flow", action="store_true", help="Print strategy flow example and exit")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.print_example_flow:
        print(json.dumps(example_signal_flow(), indent=2))
        print(json.dumps({"config": asdict(StrategyConfig())}, indent=2))
        return

    if not args.data_1m or not args.data_5m or not args.data_1h:
        raise ValueError("Provide --data-1m, --data-5m, and --data-1h or use --print-example-flow")

    frame_1m = _read_ohlcv_csv(args.data_1m)
    frame_5m = _read_ohlcv_csv(args.data_5m)
    frame_1h = _read_ohlcv_csv(args.data_1h)

    signals = generate_multi_timeframe_signals(
        frame_1m=frame_1m,
        frame_5m=frame_5m,
        frame_1h=frame_1h,
        config=StrategyConfig(),
    )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        signals.to_csv(args.out, index=False)

    tail = signals.tail(20)
    print(tail.to_string(index=False))


if __name__ == "__main__":
    main()
