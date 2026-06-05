from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

LEAKAGE_TOKENS = (
    "future",
    "target",
    "label",
    "tb_event",
    "tb_profit",
    "tb_stop",
    "split",
    "wf_fold",
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: str
    message: str
    details: dict[str, Any]


class ValidationError(RuntimeError):
    pass


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.isoformat()
    return value


def compute_config_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(_to_native(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _issue(code: str, severity: str, message: str, **details: Any) -> ValidationIssue:
    return ValidationIssue(
        code=str(code),
        severity=str(severity),
        message=str(message),
        details={str(k): _to_native(v) for k, v in details.items()},
    )


def _normalize_required_timeframes(required_timeframes: Iterable[str] | None) -> set[str]:
    if not required_timeframes:
        return set()
    return {str(tf).strip().lower() for tf in required_timeframes if str(tf).strip()}


def _volume_anomaly_summary(df: pd.DataFrame) -> dict[str, Any]:
    if "volume" not in df.columns or df.empty:
        return {
            "zero_or_negative_ratio": 0.0,
            "constant_run_ratio": 0.0,
            "synthetic_flag_ratio": 0.0,
        }

    volume = pd.to_numeric(df["volume"], errors="coerce")
    valid = volume.dropna()
    if valid.empty:
        return {
            "zero_or_negative_ratio": 1.0,
            "constant_run_ratio": 0.0,
            "synthetic_flag_ratio": 0.0,
        }

    zero_or_negative_ratio = float((valid <= 0).mean())
    same_as_prev = valid.eq(valid.shift(1))
    constant_run_ratio = float(same_as_prev.mean())

    synthetic_flag_ratio = 0.0
    if "is_gap_filled" in df.columns:
        synthetic_flag_ratio = float(pd.to_numeric(df["is_gap_filled"], errors="coerce").fillna(0).gt(0).mean())

    return {
        "zero_or_negative_ratio": zero_or_negative_ratio,
        "constant_run_ratio": constant_run_ratio,
        "synthetic_flag_ratio": synthetic_flag_ratio,
    }


def validate_dataframe_core(
    df: pd.DataFrame,
    required_columns: Iterable[str],
    key_columns: Iterable[str],
    required_timeframes: Iterable[str] | None = None,
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []

    required = [str(col) for col in required_columns]
    missing_columns = [col for col in required if col not in df.columns]
    if missing_columns:
        issues.append(
            _issue(
                "missing_required_columns",
                CRITICAL,
                "Required columns are missing from dataset.",
                missing_columns=missing_columns,
            )
        )

    summary: dict[str, Any] = {
        "row_count": int(len(df)),
        "missing_columns": missing_columns,
        "null_timestamp_count": 0,
        "duplicate_key_count": 0,
        "duplicate_key_ratio": 0.0,
        "required_timeframes": sorted(_normalize_required_timeframes(required_timeframes)),
        "available_timeframes": [],
        "missing_timeframes": [],
        "volume_anomalies": _volume_anomaly_summary(df),
    }

    if df.empty:
        issues.append(_issue("empty_dataset", CRITICAL, "Dataset is empty."))
        return issues, summary

    if "timestamp" in df.columns:
        parsed_timestamps = pd.to_datetime(df["timestamp"], errors="coerce")
        null_timestamp_count = int(parsed_timestamps.isna().sum())
        summary["null_timestamp_count"] = null_timestamp_count
        if null_timestamp_count > 0:
            issues.append(
                _issue(
                    "null_timestamp_rows",
                    CRITICAL,
                    "Rows with null or unparseable timestamps were found.",
                    null_timestamp_count=null_timestamp_count,
                )
            )

        timestamp_is_tz_aware = bool(getattr(parsed_timestamps.dt, "tz", None) is not None)
        summary["timestamp_tz_aware"] = timestamp_is_tz_aware

    keys = [col for col in key_columns if col in df.columns]
    if keys:
        duplicate_mask = df.duplicated(subset=keys, keep=False)
        duplicate_count = int(duplicate_mask.sum())
        summary["duplicate_key_count"] = duplicate_count
        summary["duplicate_key_ratio"] = float(duplicate_count / max(len(df), 1))
        if duplicate_count > 0:
            severity = CRITICAL if summary["duplicate_key_ratio"] > 0.001 else HIGH
            issues.append(
                _issue(
                    "duplicate_key_rows",
                    severity,
                    "Duplicate rows detected for uniqueness key.",
                    key_columns=keys,
                    duplicate_row_count=duplicate_count,
                    duplicate_ratio=summary["duplicate_key_ratio"],
                )
            )

    required_tfs = _normalize_required_timeframes(required_timeframes)
    if "timeframe" in df.columns:
        available_tfs = sorted(df["timeframe"].astype(str).str.lower().dropna().unique().tolist())
        summary["available_timeframes"] = available_tfs
        missing_tfs = sorted(required_tfs - set(available_tfs))
        summary["missing_timeframes"] = missing_tfs
        if missing_tfs:
            issues.append(
                _issue(
                    "missing_required_timeframes",
                    CRITICAL,
                    "One or more required timeframes are missing.",
                    missing_timeframes=missing_tfs,
                    available_timeframes=available_tfs,
                )
            )

    volume_anomalies = summary["volume_anomalies"]
    if volume_anomalies["zero_or_negative_ratio"] > 0.01:
        issues.append(
            _issue(
                "zero_or_negative_volume",
                HIGH,
                "Volume contains too many zero or negative rows.",
                zero_or_negative_ratio=volume_anomalies["zero_or_negative_ratio"],
            )
        )

    if volume_anomalies["constant_run_ratio"] > 0.95:
        issues.append(
            _issue(
                "suspicious_constant_volume",
                HIGH,
                "Volume appears nearly constant and may be synthetic.",
                constant_run_ratio=volume_anomalies["constant_run_ratio"],
            )
        )

    return issues, summary


def validate_ohlcv_integrity(
    df: pd.DataFrame,
    ohlcv_columns: Iterable[str] = ("open", "high", "low", "close", "volume"),
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    summary: dict[str, Any] = {
        "invalid_ohlcv_rows": 0,
        "nonpositive_price_rows": 0,
        "negative_volume_rows": 0,
    }

    required = [str(col) for col in ohlcv_columns]
    if any(col not in df.columns for col in required):
        missing = [col for col in required if col not in df.columns]
        issues.append(
            _issue(
                "missing_ohlcv_columns",
                CRITICAL,
                "Dataset is missing OHLCV columns required for integrity validation.",
                missing_columns=missing,
            )
        )
        return issues, summary

    prices = df[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    volume = pd.to_numeric(df["volume"], errors="coerce")

    nonpositive_price_mask = (prices <= 0).any(axis=1) | prices.isna().any(axis=1)
    invalid_high_low_mask = ~(
        (prices["high"] >= prices[["open", "close", "low"]].max(axis=1))
        & (prices["low"] <= prices[["open", "close", "high"]].min(axis=1))
    )
    negative_volume_mask = volume.isna() | volume.lt(0)
    invalid_mask = nonpositive_price_mask | invalid_high_low_mask | negative_volume_mask

    summary["invalid_ohlcv_rows"] = int(invalid_mask.sum())
    summary["nonpositive_price_rows"] = int(nonpositive_price_mask.sum())
    summary["negative_volume_rows"] = int(negative_volume_mask.sum())

    if summary["invalid_ohlcv_rows"] > 0:
        issues.append(
            _issue(
                "invalid_ohlcv_rows",
                CRITICAL,
                "OHLCV integrity checks failed for one or more rows.",
                invalid_ohlcv_rows=summary["invalid_ohlcv_rows"],
                nonpositive_price_rows=summary["nonpositive_price_rows"],
                negative_volume_rows=summary["negative_volume_rows"],
            )
        )

    return issues, summary


def validate_missing_candles(
    df: pd.DataFrame,
    timeframe: str,
    key_columns: Iterable[str] = ("symbol",),
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    summary: dict[str, Any] = {
        "timeframe": str(timeframe),
        "symbols_with_gaps": 0,
        "missing_candle_count": 0,
    }

    if df.empty or "timestamp" not in df.columns:
        return issues, summary

    freq_map = {"1m": "1min", "5m": "5min", "15m": "15min", "1h": "1h", "1d": "1D"}
    freq = freq_map.get(str(timeframe).strip().lower())
    if freq is None:
        return issues, summary

    missing_total = 0
    symbols_with_gaps = 0
    grouped = df.groupby([col for col in key_columns if col in df.columns], sort=False)
    for _, group in grouped:
        ts = pd.to_datetime(group["timestamp"], errors="coerce").dropna().sort_values().drop_duplicates()
        if len(ts) < 2:
            continue
        expected = pd.date_range(ts.iloc[0], ts.iloc[-1], freq=freq)
        missing = int(len(expected.difference(ts)))
        if missing > 0:
            missing_total += missing
            symbols_with_gaps += 1

    summary["symbols_with_gaps"] = int(symbols_with_gaps)
    summary["missing_candle_count"] = int(missing_total)

    if missing_total > 0:
        issues.append(
            _issue(
                "missing_candles_detected",
                HIGH,
                "One or more symbol streams contain missing candles.",
                missing_candle_count=summary["missing_candle_count"],
                symbols_with_gaps=summary["symbols_with_gaps"],
                timeframe=str(timeframe),
            )
        )

    return issues, summary


def sanitize_training_frame(
    df: pd.DataFrame,
    feature_columns: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if df.empty:
        return df.copy(), {"rows_in": 0, "rows_out": 0, "rows_dropped": 0}

    out = df.copy()
    rows_in = int(len(out))

    if "timestamp" in out.columns:
        out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
        out = out.dropna(subset=["timestamp"])

    ohlcv_present = [col for col in ["open", "high", "low", "close", "volume"] if col in out.columns]
    if ohlcv_present:
        for col in ohlcv_present:
            out[col] = pd.to_numeric(out[col], errors="coerce")
        prices = [col for col in ["open", "high", "low", "close"] if col in out.columns]
        if prices:
            out = out[(out[prices] > 0).all(axis=1)]
        if "volume" in out.columns:
            out = out[out["volume"] >= 0]

    if feature_columns:
        for feature in feature_columns:
            if feature in out.columns:
                out[feature] = pd.to_numeric(out[feature], errors="coerce")
        out = out.replace([np.inf, -np.inf], np.nan)
        present_features = [col for col in feature_columns if col in out.columns]
        if present_features:
            out = out.dropna(subset=present_features)

    rows_out = int(len(out))
    return out.reset_index(drop=True), {
        "rows_in": rows_in,
        "rows_out": rows_out,
        "rows_dropped": int(rows_in - rows_out),
    }


def validate_feature_matrix(frame: pd.DataFrame, feature_columns: list[str]) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    summary: dict[str, Any] = {
        "feature_count": int(len(feature_columns)),
        "missing_features": [],
        "nan_feature_rows": 0,
        "inf_feature_rows": 0,
        "fully_nan_features": [],
    }

    if not feature_columns:
        issues.append(_issue("empty_feature_list", CRITICAL, "No feature columns were supplied."))
        return issues, summary

    missing_features = [col for col in feature_columns if col not in frame.columns]
    summary["missing_features"] = missing_features
    if missing_features:
        issues.append(
            _issue(
                "missing_feature_columns",
                CRITICAL,
                "Dataset does not contain all model feature columns.",
                missing_features=missing_features,
            )
        )
        return issues, summary

    matrix = frame[feature_columns].apply(pd.to_numeric, errors="coerce")
    inf_mask = np.isinf(matrix.to_numpy(dtype=float))
    nan_rows = int(matrix.isna().any(axis=1).sum())
    inf_rows = int(inf_mask.any(axis=1).sum()) if inf_mask.size else 0

    summary["nan_feature_rows"] = nan_rows
    summary["inf_feature_rows"] = inf_rows

    fully_nan_features = [
        col
        for col in feature_columns
        if matrix[col].isna().all()
    ]
    summary["fully_nan_features"] = fully_nan_features

    if fully_nan_features:
        issues.append(
            _issue(
                "fully_nan_features",
                CRITICAL,
                "One or more feature columns are entirely NaN.",
                feature_names=fully_nan_features,
            )
        )

    if nan_rows > 0:
        issues.append(
            _issue(
                "nan_rows_in_feature_matrix",
                HIGH,
                "Feature matrix contains NaN rows before final sanitation.",
                nan_row_count=nan_rows,
                nan_row_ratio=float(nan_rows / max(len(frame), 1)),
            )
        )

    if inf_rows > 0:
        issues.append(
            _issue(
                "inf_rows_in_feature_matrix",
                HIGH,
                "Feature matrix contains inf rows before final sanitation.",
                inf_row_count=inf_rows,
                inf_row_ratio=float(inf_rows / max(len(frame), 1)),
            )
        )

    return issues, summary


def validate_feature_leakage(feature_columns: list[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    suspicious: list[str] = []

    for feature in feature_columns:
        token = str(feature).lower()
        if token in {"target_class", "target_signal", "future_return"}:
            suspicious.append(feature)
            continue
        if any(flag in token for flag in LEAKAGE_TOKENS):
            suspicious.append(feature)

    if suspicious:
        issues.append(
            _issue(
                "suspicious_feature_leakage_tokens",
                CRITICAL,
                "Feature list contains leakage-prone names.",
                suspicious_features=sorted(set(suspicious)),
            )
        )

    return issues


def validate_split_integrity(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    key_columns: Iterable[str],
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    summary: dict[str, Any] = {
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "train_max_timestamp": None,
        "test_min_timestamp": None,
        "cross_split_overlap_count": 0,
    }

    if train_df.empty or test_df.empty:
        issues.append(
            _issue(
                "empty_split",
                CRITICAL,
                "Train/test split contains an empty partition.",
                train_rows=len(train_df),
                test_rows=len(test_df),
            )
        )
        return issues, summary

    train_ts = pd.to_datetime(train_df["timestamp"], errors="coerce")
    test_ts = pd.to_datetime(test_df["timestamp"], errors="coerce")

    train_max = train_ts.max()
    test_min = test_ts.min()
    summary["train_max_timestamp"] = _to_native(train_max)
    summary["test_min_timestamp"] = _to_native(test_min)

    if pd.notna(train_max) and pd.notna(test_min) and train_max >= test_min:
        issues.append(
            _issue(
                "temporal_overlap",
                CRITICAL,
                "Temporal split overlap detected (train max >= test min).",
                train_max_timestamp=train_max,
                test_min_timestamp=test_min,
            )
        )

    keys = [col for col in key_columns if col in train_df.columns and col in test_df.columns]
    if keys:
        left = train_df[keys].copy().drop_duplicates()
        right = test_df[keys].copy().drop_duplicates()
        merged = left.merge(right, on=keys, how="inner")
        overlap_count = int(len(merged))
        summary["cross_split_overlap_count"] = overlap_count
        if overlap_count > 0:
            issues.append(
                _issue(
                    "split_key_overlap",
                    CRITICAL,
                    "Train/test overlap detected on uniqueness keys.",
                    key_columns=keys,
                    overlap_count=overlap_count,
                )
            )

    return issues, summary


def _compute_psi(train_values: pd.Series, test_values: pd.Series, bins: int = 10) -> float | None:
    train = pd.to_numeric(train_values, errors="coerce").dropna().to_numpy(dtype=float)
    test = pd.to_numeric(test_values, errors="coerce").dropna().to_numpy(dtype=float)

    if train.size < 50 or test.size < 50:
        return None

    quantiles = np.linspace(0.0, 1.0, max(2, int(bins) + 1))
    edges = np.unique(np.quantile(train, quantiles))
    if edges.size < 3:
        return None

    train_hist, _ = np.histogram(train, bins=edges)
    test_hist, _ = np.histogram(test, bins=edges)

    if train_hist.sum() <= 0 or test_hist.sum() <= 0:
        return None

    train_dist = np.clip(train_hist.astype(float) / train_hist.sum(), 1e-6, None)
    test_dist = np.clip(test_hist.astype(float) / test_hist.sum(), 1e-6, None)

    psi = np.sum((test_dist - train_dist) * np.log(test_dist / train_dist))
    if not np.isfinite(psi):
        return None
    return float(psi)


def evaluate_feature_drift(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_columns: list[str],
    psi_threshold: float = 0.25,
) -> tuple[list[ValidationIssue], dict[str, Any]]:
    issues: list[ValidationIssue] = []
    psi_values: dict[str, float] = {}

    for feature in feature_columns:
        if feature not in train_df.columns or feature not in test_df.columns:
            continue
        psi = _compute_psi(train_df[feature], test_df[feature])
        if psi is None:
            continue
        psi_values[feature] = float(psi)

    severe = sorted(
        [
            {"feature": feature, "psi": value}
            for feature, value in psi_values.items()
            if value > float(psi_threshold)
        ],
        key=lambda row: row["psi"],
        reverse=True,
    )

    if severe:
        issues.append(
            _issue(
                "feature_drift_exceeds_threshold",
                HIGH,
                "One or more features exceed PSI drift threshold.",
                psi_threshold=float(psi_threshold),
                severe_features=severe[:30],
                severe_count=len(severe),
            )
        )

    summary = {
        "psi_threshold": float(psi_threshold),
        "evaluated_feature_count": int(len(psi_values)),
        "severe_feature_count": int(len(severe)),
        "top_drift_features": severe[:30],
    }
    return issues, summary


def run_pretraining_validation(
    full_df: pd.DataFrame,
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_columns: list[str],
    required_timeframes: Iterable[str] | None = None,
    psi_threshold: float = 0.25,
    strict: bool = True,
) -> dict[str, Any]:
    issues: list[ValidationIssue] = []

    core_issues, core_summary = validate_dataframe_core(
        df=full_df,
        required_columns=["timestamp", "symbol", "timeframe", "target_class"],
        key_columns=["symbol", "timeframe", "timestamp"],
        required_timeframes=required_timeframes,
    )
    issues.extend(core_issues)

    ohlcv_issues, ohlcv_summary = validate_ohlcv_integrity(full_df)
    issues.extend(ohlcv_issues)

    gap_issues, gap_summary = validate_missing_candles(
        full_df,
        timeframe=str(full_df["timeframe"].iloc[0]) if "timeframe" in full_df.columns and not full_df.empty else "unknown",
    )
    issues.extend(gap_issues)

    feature_issues, feature_summary = validate_feature_matrix(full_df, feature_columns=feature_columns)
    issues.extend(feature_issues)

    leakage_issues = validate_feature_leakage(feature_columns)
    issues.extend(leakage_issues)

    split_issues, split_summary = validate_split_integrity(
        train_df=train_df,
        test_df=test_df,
        key_columns=["symbol", "timeframe", "timestamp"],
    )
    issues.extend(split_issues)

    drift_issues, drift_summary = evaluate_feature_drift(
        train_df=train_df,
        test_df=test_df,
        feature_columns=feature_columns,
        psi_threshold=float(psi_threshold),
    )
    issues.extend(drift_issues)

    issues_payload = [asdict(issue) for issue in issues]
    severity_counts = {
        CRITICAL: int(sum(1 for issue in issues if issue.severity == CRITICAL)),
        HIGH: int(sum(1 for issue in issues if issue.severity == HIGH)),
        MEDIUM: int(sum(1 for issue in issues if issue.severity == MEDIUM)),
        LOW: int(sum(1 for issue in issues if issue.severity == LOW)),
    }

    report = {
        "status": "failed" if severity_counts[CRITICAL] > 0 else "passed",
        "strict_mode": bool(strict),
        "severity_counts": severity_counts,
        "issues": issues_payload,
        "summaries": {
            "core": core_summary,
            "ohlcv": ohlcv_summary,
            "gaps": gap_summary,
            "features": feature_summary,
            "split": split_summary,
            "drift": drift_summary,
        },
    }

    if strict and severity_counts[CRITICAL] > 0:
        raise ValidationError(
            "Pre-training validation failed with critical issues: "
            + ", ".join(issue.code for issue in issues if issue.severity == CRITICAL)
        )

    return report
