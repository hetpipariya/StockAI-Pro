"""Time Intelligence Engine for intraday session-aware signal timing."""

from __future__ import annotations

from datetime import date, datetime, time as dt_time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

EXCHANGE_TZ = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = dt_time(9, 15)
MARKET_CLOSE = dt_time(15, 30)
SESSION_OPEN_END = dt_time(10, 15)
SESSION_CLOSE_START = dt_time(14, 30)

DAY_BIAS_SCORE = {
    0: 0.42,  # Monday: slow/trap-prone start
    1: 0.55,
    2: 0.58,
    3: 0.62,
    4: 0.46,  # Friday: profit-booking volatility
}

SESSION_SCORE = {
    "OPEN": 0.58,
    "MID": 0.38,
    "CLOSE": 0.72,
}

BUCKET_SCORE = {
    "OPENING_SPIKE": 0.56,
    "TREND_FORMATION": 0.74,
    "SIDEWAYS": 0.32,
    "SETUP_PHASE": 0.57,
    "BREAKOUT_REVERSAL": 0.76,
    "OFF_HOURS": 0.20,
}

CONFIRMATION_THRESHOLD = {
    "OPEN": 0.72,
    "MID": 0.75,
    "CLOSE": 0.60,
}


def _clip01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))


def _normalize_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None

    if isinstance(ts, pd.Timestamp):
        if ts.tzinfo is None:
            return ts.tz_localize(EXCHANGE_TZ).to_pydatetime()
        return ts.tz_convert(EXCHANGE_TZ).to_pydatetime()

    return None


def _extract_latest_timestamp(ohlcv_df: pd.DataFrame | None) -> datetime:
    if ohlcv_df is not None and not ohlcv_df.empty:
        for column in ("time", "timestamp", "datetime", "date"):
            if column in ohlcv_df.columns:
                values = ohlcv_df[column].dropna().tolist()
                for raw_value in reversed(values):
                    normalized = _normalize_timestamp(raw_value)
                    if normalized is not None:
                        return normalized

        if isinstance(ohlcv_df.index, pd.DatetimeIndex) and len(ohlcv_df.index) > 0:
            index_ts = ohlcv_df.index[-1]
            if index_ts.tzinfo is None:
                return index_ts.tz_localize(EXCHANGE_TZ).to_pydatetime()
            return index_ts.tz_convert(EXCHANGE_TZ).to_pydatetime()

    now_local = datetime.now(tz=EXCHANGE_TZ)
    return now_local.replace(hour=11, minute=45, second=0, microsecond=0)


def _classify_session(now_local: datetime) -> str:
    current = now_local.time()
    if MARKET_OPEN <= current < SESSION_OPEN_END:
        return "OPEN"
    if SESSION_CLOSE_START <= current <= MARKET_CLOSE:
        return "CLOSE"
    return "MID"


def _classify_time_bucket(now_local: datetime) -> str:
    current = now_local.time()

    if dt_time(9, 15) <= current < dt_time(9, 30):
        return "OPENING_SPIKE"
    if dt_time(9, 30) <= current < dt_time(10, 30):
        return "TREND_FORMATION"
    if dt_time(10, 30) <= current < dt_time(13, 30):
        return "SIDEWAYS"
    if dt_time(13, 30) <= current < dt_time(14, 30):
        return "SETUP_PHASE"
    if dt_time(14, 30) <= current <= dt_time(15, 30):
        return "BREAKOUT_REVERSAL"
    return "OFF_HOURS"


def _last_thursday(year: int, month: int) -> date:
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)

    last_day = next_month - timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7
    return last_day - timedelta(days=offset)


def _expiry_info(now_local: datetime) -> tuple[bool, str]:
    is_thursday = now_local.weekday() == 3
    if not is_thursday:
        return False, "NONE"

    monthly_expiry_day = _last_thursday(now_local.year, now_local.month)
    if now_local.date() == monthly_expiry_day:
        return True, "MONTHLY"

    return True, "WEEKLY"


def compute_time_intelligence(ohlcv_df: pd.DataFrame | None) -> dict[str, Any]:
    """Compute session-, calendar-, and bucket-aware time intelligence signals."""
    now_local = _extract_latest_timestamp(ohlcv_df)

    session = _classify_session(now_local)
    time_bucket = _classify_time_bucket(now_local)
    day_of_week = int(now_local.weekday())
    day_bias_score = float(DAY_BIAS_SCORE.get(day_of_week, 0.50))

    expiry_flag, expiry_type = _expiry_info(now_local)

    session_score = float(SESSION_SCORE.get(session, 0.50))
    bucket_score = float(BUCKET_SCORE.get(time_bucket, 0.50))
    expiry_score = 0.35 if expiry_flag else 0.65

    time_score = _clip01(
        (0.30 * session_score)
        + (0.30 * bucket_score)
        + (0.20 * day_bias_score)
        + (0.20 * expiry_score)
    )

    if time_bucket == "OFF_HOURS":
        time_bias = "OFF_HOURS"
    elif expiry_flag:
        time_bias = "HIGH_VOLATILITY"
    elif session == "OPEN":
        time_bias = "HIGH_VOLATILITY"
    elif session == "MID" and time_bucket == "SIDEWAYS":
        time_bias = "LOW_VOLATILITY"
    elif session == "CLOSE":
        time_bias = "TREND_CONTINUATION"
    else:
        time_bias = "NEUTRAL"

    if time_bucket == "OFF_HOURS":
        trade_mode = "NO_TRADE"
        position_size_factor = 0.50
    elif session == "OPEN":
        trade_mode = "STRICT_CONFIRMATION"
        position_size_factor = 0.90
    elif session == "MID":
        trade_mode = "TREND_ONLY"
        position_size_factor = 0.85
    else:
        trade_mode = "TREND_CONTINUATION"
        position_size_factor = 1.00

    if expiry_flag:
        position_size_factor = min(position_size_factor, 0.70)

    return {
        "session": session,
        "time_bucket": time_bucket,
        "day_of_week": day_of_week,
        "day_bias_score": round(_clip01(day_bias_score), 4),
        "expiry_flag": bool(expiry_flag),
        "expiry_type": expiry_type,
        "time_score": round(time_score, 4),
        "time_bias": time_bias,
        "trade_mode": trade_mode,
        "confirmation_threshold": float(CONFIRMATION_THRESHOLD.get(session, 0.65)),
        "position_size_factor": round(float(_clip01(position_size_factor)), 4),
        "components": {
            "session": round(_clip01(session_score), 4),
            "time_bucket": round(_clip01(bucket_score), 4),
            "day_of_week": round(_clip01(day_bias_score), 4),
            "expiry": round(_clip01(expiry_score), 4),
        },
        "timestamp": now_local.isoformat(),
    }
