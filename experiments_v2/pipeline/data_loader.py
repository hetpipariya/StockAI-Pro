from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import pandas as pd

LOGGER = logging.getLogger(__name__)

REQUIRED_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

_TIMESTAMP_ALIASES = {"timestamp", "date", "datetime", "time"}
_SYMBOL_ALIASES = {"symbol", "ticker"}
_TIMEFRAME_ALIASES = {"timeframe", "tf", "interval"}

_FILENAME_PATTERN = re.compile(
    r"^(?P<symbol>[A-Za-z0-9.&_-]+?)(?:[_-](?P<timeframe>\d+[mhd]))?(?:[_-](?:raw|processed))?\.csv$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SymbolBatch:
    symbol: str
    frames_by_timeframe: dict[str, pd.DataFrame]
    source_files: dict[str, list[str]]


def _safe_read_csv(csv_path: Path) -> pd.DataFrame:
    allowed = {
        "timestamp",
        "date",
        "datetime",
        "time",
        "symbol",
        "ticker",
        "timeframe",
        "tf",
        "interval",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }

    usecols = lambda col: str(col).strip().lower() in allowed

    try:
        return pd.read_csv(
            csv_path,
            usecols=usecols,
            low_memory=False,
        )
    except Exception:
        # Python engine is slower but more resilient on malformed oversized lines.
        return pd.read_csv(
            csv_path,
            usecols=usecols,
            engine="python",
            on_bad_lines="skip",
        )


def _normalize_symbol(symbol: str) -> str:
    token = str(symbol).strip().upper().replace(".NS", "")
    token = re.sub(r"[_-](RAW|PROCESSED)$", "", token, flags=re.IGNORECASE)
    token = re.sub(r"[-_]EQ$", "", token, flags=re.IGNORECASE)
    return token


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map = {}
    for col in df.columns:
        key = str(col).strip().lower()
        if key in _TIMESTAMP_ALIASES:
            rename_map[col] = "timestamp"
        elif key in _SYMBOL_ALIASES:
            rename_map[col] = "symbol"
        elif key in _TIMEFRAME_ALIASES:
            rename_map[col] = "timeframe"
        elif key in {"open", "high", "low", "close", "volume"}:
            rename_map[col] = key
    return df.rename(columns=rename_map)


def _infer_symbol_timeframe(csv_path: Path, default_timeframe: str | None) -> tuple[str, str]:
    match = _FILENAME_PATTERN.match(csv_path.name)
    inferred_symbol = csv_path.stem.upper()
    inferred_tf = default_timeframe or "unknown"

    if match:
        inferred_symbol = match.group("symbol").upper()
        if match.group("timeframe"):
            inferred_tf = match.group("timeframe").lower()

    inferred_symbol = _normalize_symbol(inferred_symbol)
    return inferred_symbol, inferred_tf


def _load_single_csv(csv_path: Path, default_timeframe: str | None) -> pd.DataFrame:
    frame = _safe_read_csv(csv_path)
    frame = _normalize_columns(frame)

    symbol_hint, timeframe_hint = _infer_symbol_timeframe(csv_path, default_timeframe)

    if "symbol" not in frame.columns:
        frame["symbol"] = symbol_hint
    if "timeframe" not in frame.columns:
        frame["timeframe"] = timeframe_hint

    missing_cols = [col for col in REQUIRED_COLUMNS if col not in frame.columns]
    if missing_cols:
        raise ValueError(
            f"CSV {csv_path} missing required columns: {missing_cols}. "
            "Expected at least timestamp, open, high, low, close, volume."
        )

    selected = frame[
        ["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe"]
    ].copy()

    for col in ["open", "high", "low", "close", "volume"]:
        selected[col] = pd.to_numeric(selected[col], errors="coerce").astype("float32")

    selected["source_file"] = csv_path.name
    return selected


def _coerce_loaded_frame(frame: pd.DataFrame, symbol_filter: str | None = None) -> pd.DataFrame:
    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).map(_normalize_symbol)
    out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()

    if symbol_filter is not None:
        out = out[out["symbol"] == symbol_filter]

    out = out.dropna(subset=["timestamp", "symbol", "timeframe"])
    if out.empty:
        return out

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float32")

    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    out = out.sort_values(["symbol", "timeframe", "timestamp"]).drop_duplicates(
        subset=["symbol", "timeframe", "timestamp"],
        keep="last",
    )

    return out.reset_index(drop=True)


def _discover_csvs(raw_root: Path, timeframe_folders: Iterable[str]) -> list[tuple[Path, str | None]]:
    discovered: list[tuple[Path, str | None]] = []

    for tf in timeframe_folders:
        tf_dir = raw_root / tf
        if not tf_dir.exists() or not tf_dir.is_dir():
            continue
        for path in sorted(tf_dir.glob("*.csv")):
            discovered.append((path, tf.lower()))

    # Allow direct raw_root/*.csv fallback.
    for path in sorted(raw_root.glob("*.csv")):
        discovered.append((path, None))

    return discovered


def _build_symbol_file_map(
    csv_files: list[tuple[Path, str | None]],
    symbol_allowlist: Iterable[str] | None = None,
) -> dict[str, list[tuple[Path, str | None]]]:
    symbol_set = None
    if symbol_allowlist is not None:
        symbol_set = {
            _normalize_symbol(token)
            for token in symbol_allowlist
            if str(token).strip()
        }

    grouped: dict[str, list[tuple[Path, str | None]]] = {}
    for csv_path, default_tf in csv_files:
        inferred_symbol, _ = _infer_symbol_timeframe(csv_path, default_tf)
        if symbol_set is not None and inferred_symbol not in symbol_set:
            continue
        grouped.setdefault(inferred_symbol, []).append((csv_path, default_tf))

    return grouped


def iter_symbol_timeframe_batches(
    raw_root: str | Path,
    timeframe_folders: Iterable[str] = ("1m", "5m", "1h"),
    symbol_allowlist: Iterable[str] | None = None,
    max_files_per_timeframe: int | None = None,
    required_timeframes: Iterable[str] | None = None,
) -> Iterator[SymbolBatch]:
    """Yield one symbol batch at a time for memory-safe processing."""
    root = Path(raw_root)
    if not root.exists():
        raise FileNotFoundError(f"Raw data directory not found: {root}")

    csv_files = _discover_csvs(root, timeframe_folders)
    if max_files_per_timeframe is not None and max_files_per_timeframe > 0:
        limited: list[tuple[Path, str | None]] = []
        by_tf: dict[str, int] = {}
        for csv_path, tf in csv_files:
            key = (tf or "unknown").lower()
            current = by_tf.get(key, 0)
            if current >= int(max_files_per_timeframe):
                continue
            by_tf[key] = current + 1
            limited.append((csv_path, tf))
        csv_files = limited

    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found under {root}. Place files in raw/1m, raw/5m, raw/1h or raw/."
        )

    required_set = {
        str(tf).strip().lower()
        for tf in required_timeframes or ()
        if str(tf).strip()
    }
    symbol_map = _build_symbol_file_map(
        csv_files=csv_files,
        symbol_allowlist=symbol_allowlist,
    )

    if not symbol_map:
        return

    for symbol in sorted(symbol_map.keys()):
        tf_frames: dict[str, list[pd.DataFrame]] = {}
        tf_sources: dict[str, list[str]] = {}

        for csv_path, default_tf in symbol_map[symbol]:
            try:
                loaded = _load_single_csv(csv_path=csv_path, default_timeframe=default_tf)
                loaded = _coerce_loaded_frame(loaded, symbol_filter=symbol)
                if loaded.empty:
                    continue

                for timeframe, tf_block in loaded.groupby("timeframe", sort=False):
                    tf_key = str(timeframe).lower()
                    tf_frames.setdefault(tf_key, []).append(tf_block.copy())
                    tf_sources.setdefault(tf_key, []).append(csv_path.name)
            except Exception as exc:
                LOGGER.warning("Skipping unreadable file %s: %s", csv_path, exc)

        merged_by_timeframe: dict[str, pd.DataFrame] = {}
        for timeframe, blocks in tf_frames.items():
            if not blocks:
                continue
            merged = pd.concat(blocks, ignore_index=True, copy=False)
            merged = merged.sort_values("timestamp").drop_duplicates(
                subset=["timestamp"],
                keep="last",
            )
            merged = merged[["timestamp", "open", "high", "low", "close", "volume", "symbol", "timeframe", "source_file"]]

            for col in ["open", "high", "low", "close", "volume"]:
                merged[col] = pd.to_numeric(merged[col], errors="coerce").astype("float32")

            merged = merged.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
            if merged.empty:
                continue

            merged_by_timeframe[timeframe] = merged.reset_index(drop=True)

        if not merged_by_timeframe:
            continue

        if required_set and not required_set.issubset(set(merged_by_timeframe.keys())):
            continue

        yield SymbolBatch(
            symbol=symbol,
            frames_by_timeframe=merged_by_timeframe,
            source_files={
                tf: sorted(set(files))
                for tf, files in tf_sources.items()
            },
        )


def load_ohlcv_csv_folder(
    raw_root: str | Path,
    timeframe_folders: Iterable[str] = ("1m", "5m", "1h"),
    symbol_allowlist: Iterable[str] | None = None,
    max_files_per_timeframe: int | None = None,
) -> pd.DataFrame:
    """Load OHLCV rows from CSV files under raw_root/timeframe folders.

    Supported naming styles:
    - data/raw/5m/RELIANCE.csv
    - data/raw/RELIANCE_5m_processed.csv
    - data/raw/RELIANCE_5m.csv
    """
    frames: list[pd.DataFrame] = []
    for symbol_batch in iter_symbol_timeframe_batches(
        raw_root=raw_root,
        timeframe_folders=timeframe_folders,
        symbol_allowlist=symbol_allowlist,
        max_files_per_timeframe=max_files_per_timeframe,
    ):
        for frame in symbol_batch.frames_by_timeframe.values():
            if frame is not None and not frame.empty:
                frames.append(frame)

    if not frames:
        raise RuntimeError("No valid CSV files could be loaded from raw data directory.")

    merged = pd.concat(frames, ignore_index=True, copy=False)
    merged = _coerce_loaded_frame(merged)

    merged["symbol"] = merged["symbol"].astype("category")
    merged["timeframe"] = merged["timeframe"].astype("category")
    merged["source_file"] = merged["source_file"].astype("category")

    merged = merged.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    return merged
