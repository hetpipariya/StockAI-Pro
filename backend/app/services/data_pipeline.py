"""
data_pipeline.py
================
Full ML data pipeline for StockAI Pro — 100-stock NSE universe.

Usage:
    python -m backend.app.services.data_pipeline                      # full watchlist
    python -m backend.app.services.data_pipeline --ticker INFY.NS     # single ticker
    python -m backend.app.services.data_pipeline --validate           # validate tickers only

Config (env vars or .env):
    PIPELINE_YEARS   : years of history to download (default: 5)
    PIPELINE_WORKERS : multiprocessing worker count  (default: 6)
"""

from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    raise ImportError("yfinance is required: pip install yfinance")

from backend.app.services.ticker_map import TICKERS, TICKER_NAMES, WATCHLIST

# ── logging ───────────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(processName)s – %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "data_pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

# ── config ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]          # backend/app/
RAW_DIR  = BASE_DIR / "cache" / "raw_data"
FEAT_DIR = BASE_DIR / "cache" / "features"
YEARS    = int(os.getenv("PIPELINE_YEARS", "5"))
WORKERS  = int(os.getenv("PIPELINE_WORKERS", "6"))

RAW_DIR.mkdir(parents=True, exist_ok=True)
FEAT_DIR.mkdir(parents=True, exist_ok=True)

# Canonical feature column order (ensures alignment across all CSVs)
FEATURE_COLUMNS = [
    "open", "high", "low", "close", "volume",
    "ema9", "ema15", "rsi",
    "macd", "macd_signal", "macd_hist",
    "vwap", "supertrend_dir", "adx",
    "bb_upper", "bb_mid", "bb_lower", "bb_width",
    "atr", "obv",
    "stoch_k", "stoch_d",
    "ich_tenkan", "ich_kijun", "ich_senkou_a", "ich_senkou_b",
    "target",
]

MIN_ROWS_REQUIRED = 200   # skip tickers with too little history


# ══════════════════════════════════════════════════════════════════════════════
# 0. TICKER VALIDATION
# ══════════════════════════════════════════════════════════════════════════════

def validate_ticker(ticker: str) -> bool:
    """Quick check: does yfinance return any info for this ticker?"""
    try:
        info = yf.Ticker(ticker).info
        # yfinance returns empty or stub dict for invalid tickers
        if not info or info.get("regularMarketPrice") is None:
            return False
        return True
    except Exception:
        return False


def validate_all_tickers(tickers: list[str], workers: int = WORKERS) -> tuple[list[str], list[str]]:
    """Validate tickers in parallel. Returns (valid, invalid) lists."""
    log.info("Validating %d tickers …", len(tickers))
    with multiprocessing.Pool(processes=workers) as pool:
        results = pool.map(validate_ticker, tickers)
    valid   = [t for t, ok in zip(tickers, results) if ok]
    invalid = [t for t, ok in zip(tickers, results) if not ok]
    if invalid:
        log.warning("INVALID/DELISTED tickers (%d): %s", len(invalid), invalid)
    log.info("Validation done: %d valid, %d invalid", len(valid), len(invalid))
    return valid, invalid


# ══════════════════════════════════════════════════════════════════════════════
# 1. DOWNLOADER
# ══════════════════════════════════════════════════════════════════════════════

def download_ticker(ticker: str, years: int = YEARS) -> bool:
    """Download daily OHLCV for one ticker. Idempotent — skips if file < 12 h old."""
    out_path = RAW_DIR / f"{ticker}.csv"

    if out_path.exists():
        age_hours = (time.time() - out_path.stat().st_mtime) / 3600
        if age_hours < 12:
            log.info("SKIP  %s – cached (%.1f h old)", ticker, age_hours)
            return True

    end   = datetime.today()
    start = end - timedelta(days=years * 365)

    try:
        df = yf.download(
            ticker,
            start=start.strftime("%Y-%m-%d"),
            end=end.strftime("%Y-%m-%d"),
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )

        if df.empty:
            log.warning("EMPTY %s – no data returned", ticker)
            return False

        if len(df) < MIN_ROWS_REQUIRED:
            log.warning("SHORT %s – only %d rows (min %d)", ticker, len(df), MIN_ROWS_REQUIRED)
            return False

        # Flatten MultiIndex columns if present (yfinance >= 0.2.x)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0].lower() for col in df.columns]
        else:
            df.columns = [c.lower() for c in df.columns]

        df.index.name = "date"
        df.to_csv(out_path)
        log.info("OK    %s – %d rows → %s", ticker, len(df), out_path.name)
        return True

    except Exception as exc:
        log.error("FAIL  %s – %s", ticker, exc)
        return False


def download_all(tickers: list[str], workers: int = WORKERS) -> dict[str, bool]:
    """Download all tickers using a process pool."""
    log.info("Downloading %d tickers with %d workers …", len(tickers), workers)
    with multiprocessing.Pool(processes=workers) as pool:
        results = pool.map(download_ticker, tickers)
    return dict(zip(tickers, results))


# ══════════════════════════════════════════════════════════════════════════════
# 2. INDICATOR ENGINEERING (pure pandas/numpy — no external TA library needed)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _rsi(s: pd.Series, period: int = 14) -> pd.Series:
    delta = s.diff()
    gain  = delta.clip(lower=0)
    loss  = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100 - 100 / (1 + rs)


def _macd(s: pd.Series, fast=12, slow=26, signal=9):
    ema_fast   = _ema(s, fast)
    ema_slow   = _ema(s, slow)
    macd_line  = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram  = macd_line - signal_line
    return macd_line, signal_line, histogram


def _vwap(df: pd.DataFrame) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3
    return (typical * df["volume"]).cumsum() / df["volume"].cumsum()


def _bollinger_bands(s: pd.Series, period: int = 20, std_dev: float = 2.0):
    sma   = s.rolling(period).mean()
    std   = s.rolling(period).std()
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    return upper, sma, lower


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"]  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=period - 1, adjust=False).mean()


def _obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def _adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    plus_dm  = (df["high"].diff()).clip(lower=0)
    minus_dm = (-df["low"].diff()).clip(lower=0)
    mask = plus_dm >= minus_dm
    plus_dm  = plus_dm.where(mask, 0)
    minus_dm = minus_dm.where(~mask, 0)
    atr_s    = _atr(df, period)
    plus_di  = 100 * _ema(plus_dm, period)  / (atr_s + 1e-10)
    minus_di = 100 * _ema(minus_dm, period) / (atr_s + 1e-10)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    return dx.ewm(com=period - 1, adjust=False).mean()


def _stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min  = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    stoch_k  = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-10)
    stoch_d  = stoch_k.rolling(d_period).mean()
    return stoch_k, stoch_d


def _supertrend(df: pd.DataFrame, period: int = 7, multiplier: float = 3.0) -> pd.Series:
    """SuperTrend direction: +1 (bullish) / -1 (bearish)."""
    hl2   = (df["high"] + df["low"]) / 2
    atr_s = _atr(df, period)
    upper = hl2 + multiplier * atr_s
    lower = hl2 - multiplier * atr_s

    supertrend = pd.Series(index=df.index, dtype=float)
    direction  = pd.Series(index=df.index, dtype=float)

    for i in range(1, len(df)):
        cl = df["close"].iloc[i]
        prev_st = supertrend.iloc[i - 1]
        prev_cl = df["close"].iloc[i - 1]
        _up  = upper.iloc[i]
        _lo  = lower.iloc[i]
        prev_up = upper.iloc[i - 1]
        prev_lo = lower.iloc[i - 1]
        _final_up = min(_up, prev_up) if prev_cl > prev_up else _up
        _final_lo = max(_lo, prev_lo) if prev_cl < prev_lo else _lo
        if pd.isna(prev_st):
            supertrend.iloc[i] = _final_up
            direction.iloc[i]  = -1
        elif prev_st == prev_up:
            if cl <= _final_up:
                supertrend.iloc[i] = _final_up
                direction.iloc[i]  = -1
            else:
                supertrend.iloc[i] = _final_lo
                direction.iloc[i]  =  1
        else:
            if cl >= _final_lo:
                supertrend.iloc[i] = _final_lo
                direction.iloc[i]  =  1
            else:
                supertrend.iloc[i] = _final_up
                direction.iloc[i]  = -1

    return direction.fillna(-1)


def _ichimoku(df: pd.DataFrame):
    high = df["high"]
    low  = df["low"]
    tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
    kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    # NOTE: chikou (shift -26) creates NaN at tail — we exclude it to keep more rows
    return tenkan, kijun, senkou_a, senkou_b


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all technical indicators to a raw OHLCV DataFrame."""
    df = df.copy()

    df["ema9"]  = _ema(df["close"], 9)
    df["ema15"] = _ema(df["close"], 15)
    df["rsi"]   = _rsi(df["close"], 14)

    df["macd"], df["macd_signal"], df["macd_hist"] = _macd(df["close"])
    df["vwap"] = _vwap(df)

    df["supertrend_dir"] = _supertrend(df, period=7, multiplier=3.0)

    df["bb_upper"], df["bb_mid"], df["bb_lower"] = _bollinger_bands(df["close"])
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / (df["bb_mid"] + 1e-10)

    df["atr"]  = _atr(df)
    df["obv"]  = _obv(df)
    df["adx"]  = _adx(df)

    df["stoch_k"], df["stoch_d"] = _stochastic(df)

    df["ich_tenkan"], df["ich_kijun"], df["ich_senkou_a"], df["ich_senkou_b"] = _ichimoku(df)

    return df


# ══════════════════════════════════════════════════════════════════════════════
# 3. TARGET + SAVE
# ══════════════════════════════════════════════════════════════════════════════

def build_features(ticker: str) -> bool:
    """Load raw CSV → indicators → target → save aligned feature CSV."""
    raw_path  = RAW_DIR  / f"{ticker}.csv"
    feat_path = FEAT_DIR / f"{ticker}_features.csv"

    if not raw_path.exists():
        log.warning("MISSING raw data for %s", ticker)
        return False

    try:
        df = pd.read_csv(raw_path, index_col="date", parse_dates=True)
        df.columns = [c.lower() for c in df.columns]

        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            log.error("BAD COLUMNS %s: %s", ticker, df.columns.tolist())
            return False

        df = df[list(required)].dropna()

        if len(df) < MIN_ROWS_REQUIRED:
            log.warning("TOO SHORT %s – %d rows after cleaning", ticker, len(df))
            return False

        df = compute_indicators(df)

        # target: 1 if next-day close > today close, else 0
        df["target"] = (df["close"].shift(-1) > df["close"]).astype(int)

        df = df.dropna()

        # Align columns to canonical order (safety for notebook concat)
        available = [c for c in FEATURE_COLUMNS if c in df.columns]
        df = df[available]

        if len(df) < 100:
            log.warning("TOO FEW ROWS after NaN drop: %s – %d rows", ticker, len(df))
            return False

        df.to_csv(feat_path)
        log.info("FEAT  %s – %d rows, %d cols → %s",
                 ticker, len(df), len(df.columns), feat_path.name)
        return True

    except Exception as exc:
        log.error("FEAT FAIL %s – %s", ticker, exc)
        return False


def build_all_features(tickers: list[str], workers: int = WORKERS) -> dict[str, bool]:
    """Build feature CSVs for all tickers using multiprocessing."""
    log.info("Building features for %d tickers …", len(tickers))
    with multiprocessing.Pool(processes=workers) as pool:
        results = pool.map(build_features, tickers)
    return dict(zip(tickers, results))


# ══════════════════════════════════════════════════════════════════════════════
# 4. FULL PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(
    tickers: list[str] | None = None,
    workers: int = WORKERS,
    skip_validation: bool = False,
):
    """Run end-to-end: (optional validate) → download → feature engineering."""
    tickers = tickers or TICKERS
    t0 = time.time()

    log.info("═" * 60)
    log.info("StockAI Pro – ML Data Pipeline v2  (workers=%d)", workers)
    log.info("Universe: %d tickers", len(tickers))
    log.info("History : %d years", YEARS)
    log.info("Output  : %s", BASE_DIR / "cache")
    log.info("═" * 60)

    # Step 0: Validate (optional)
    if not skip_validation and len(tickers) > 10:
        valid_tickers, invalid_tickers = validate_all_tickers(tickers, workers)
        if invalid_tickers:
            log.warning("Skipping %d invalid tickers: %s", len(invalid_tickers), invalid_tickers)
        tickers = valid_tickers
    else:
        log.info("Skipping ticker validation (small list or --skip-validation)")

    # Step 1: Download
    dl_results = download_all(tickers, workers)
    ok_dl   = [t for t, v in dl_results.items() if v]
    fail_dl = [t for t, v in dl_results.items() if not v]
    log.info("Download: %d OK, %d FAILED", len(ok_dl), len(fail_dl))
    if fail_dl:
        log.warning("Failed downloads: %s", fail_dl)

    # Step 2: Feature engineering
    feat_results = build_all_features(ok_dl, workers)
    ok_feat   = [t for t, v in feat_results.items() if v]
    fail_feat = [t for t, v in feat_results.items() if not v]

    elapsed = time.time() - t0

    # Summary
    log.info("═" * 60)
    log.info("PIPELINE COMPLETE in %.1f s", elapsed)
    log.info("  Downloads : %d OK / %d failed", len(ok_dl), len(fail_dl))
    log.info("  Features  : %d OK / %d failed", len(ok_feat), len(fail_feat))
    log.info("  Output    : %s", FEAT_DIR)
    if fail_dl:
        log.info("  Failed DL : %s", fail_dl)
    if fail_feat:
        log.info("  Failed FE : %s", fail_feat)
    log.info("═" * 60)

    return ok_feat


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StockAI Pro – ML Data Pipeline")
    parser.add_argument("--ticker", nargs="*", default=None,
                        help="One or more tickers (e.g. INFY.NS BEL.NS). Default: full 100-stock universe.")
    parser.add_argument("--workers", type=int, default=WORKERS,
                        help=f"Multiprocessing workers (default: {WORKERS})")
    parser.add_argument("--years",   type=int, default=YEARS,
                        help=f"Years of history (default: {YEARS})")
    parser.add_argument("--validate", action="store_true",
                        help="Only validate tickers, don't download/build")
    parser.add_argument("--skip-validation", action="store_true",
                        help="Skip ticker validation step")
    args = parser.parse_args()

    YEARS = args.years

    if args.validate:
        valid, invalid = validate_all_tickers(args.ticker or TICKERS, args.workers)
        print(f"\n✓ Valid   ({len(valid)}): {valid}")
        print(f"✗ Invalid ({len(invalid)}): {invalid}")
    else:
        run_pipeline(
            tickers=args.ticker,
            workers=args.workers,
            skip_validation=args.skip_validation,
        )
