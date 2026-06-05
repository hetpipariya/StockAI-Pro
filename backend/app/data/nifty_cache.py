from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
NIFTY_DATA_ROOT = REPO_ROOT / "data" / "nifty"
NIFTY_DAILY_DIR = NIFTY_DATA_ROOT / "daily"
NIFTY_1H_DIR = NIFTY_DATA_ROOT / "1h"
NIFTY_5M_DIR = NIFTY_DATA_ROOT / "5m"

CANONICAL_FILENAMES: dict[Literal["daily", "1h", "5m"], str] = {
    "daily": "nifty_daily.csv",
    "1h": "nifty_1h.csv",
    "5m": "nifty_5m.csv",
}

VALIDATION_REPORT_FILENAMES: dict[Literal["daily", "1h", "5m"], str] = {
    "daily": "validation_report.json",
    "1h": "validation_report.json",
    "5m": "validation_report.json",
}

METADATA_FILENAMES: dict[Literal["daily", "1h", "5m"], str] = {
    "daily": "metadata.json",
    "1h": "metadata.json",
    "5m": "metadata.json",
}


def ensure_nifty_dirs() -> None:
    for path in (NIFTY_DAILY_DIR, NIFTY_1H_DIR, NIFTY_5M_DIR):
        path.mkdir(parents=True, exist_ok=True)


def _json_safe(value):
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def canonical_path(granularity: Literal["daily", "1h", "5m"]) -> Path:
    ensure_nifty_dirs()
    return NIFTY_DATA_ROOT / granularity / CANONICAL_FILENAMES[granularity]


def metadata_path(granularity: Literal["daily", "1h", "5m"]) -> Path:
    ensure_nifty_dirs()
    return NIFTY_DATA_ROOT / granularity / METADATA_FILENAMES[granularity]


def validation_report_path(granularity: Literal["daily", "1h", "5m"]) -> Path:
    ensure_nifty_dirs()
    return NIFTY_DATA_ROOT / granularity / VALIDATION_REPORT_FILENAMES[granularity]


def write_metadata(granularity: Literal["daily", "1h", "5m"], metadata: dict[str, object]) -> None:
    path = metadata_path(granularity)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(_json_safe({"generated_at": datetime.now().isoformat(), **metadata}), handle, indent=2)


def write_validation_report(granularity: Literal["daily", "1h", "5m"], report: dict[str, object]) -> None:
    path = validation_report_path(granularity)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(_json_safe({"generated_at": datetime.now().isoformat(), **report}), handle, indent=2)
