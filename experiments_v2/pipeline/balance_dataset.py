from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

LABEL_TO_CLASS = {"SELL": -1, "HOLD": 0, "BUY": 1}
CLASS_TO_LABEL = {value: key for key, value in LABEL_TO_CLASS.items()}
CLASS_ORDER = [-1, 0, 1]


@dataclass
class BalanceConfig:
    input_path: Path
    output_path: Path
    report_path: Path
    comparison_path: Path
    target_hold_ratio: float = 0.55
    hold_ratio_lower: float = 0.50
    hold_ratio_upper: float = 0.60
    balance_split_only: bool = True
    split_column: str = "split"
    train_split_value: str = "train"
    include_unbalanced_rows_in_output: bool = False
    oversample_method: str = "temporal_smote"
    random_state: int = 42


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, (np.generic,)):
        return value.item()
    return value


def _assert_required_columns(df: pd.DataFrame) -> None:
    required = {"timestamp", "symbol", "timeframe", "target_class"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Dataset missing required columns: {missing}")


def _load_labeled_dataset(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input dataset not found: {path}")

    df = pd.read_csv(path, low_memory=False)
    _assert_required_columns(df)

    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()
    out["target_class"] = pd.to_numeric(out["target_class"], errors="coerce")

    out = out.dropna(subset=["timestamp", "symbol", "timeframe", "target_class"]).copy()
    out["target_class"] = out["target_class"].astype(int)
    out = out[out["target_class"].isin(CLASS_ORDER)].copy()

    out = out.sort_values(["timeframe", "symbol", "timestamp"]).reset_index(drop=True)
    return out


def _distribution_table(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    if df.empty:
        columns = [
            *group_cols,
            "sell_count",
            "hold_count",
            "buy_count",
            "rows",
            "sell_pct",
            "hold_pct",
            "buy_pct",
            "minority_pct",
        ]
        return pd.DataFrame(columns=columns)

    if group_cols:
        grouped = (
            df.groupby(group_cols + ["target_class"], observed=True)
            .size()
            .unstack(fill_value=0)
        )
    else:
        grouped = pd.DataFrame(
            [{label: int((df["target_class"] == label).sum()) for label in CLASS_ORDER}]
        )

    for label in CLASS_ORDER:
        if label not in grouped.columns:
            grouped[label] = 0

    grouped = grouped[CLASS_ORDER].rename(
        columns={-1: "sell_count", 0: "hold_count", 1: "buy_count"}
    )
    grouped["rows"] = grouped[["sell_count", "hold_count", "buy_count"]].sum(axis=1)

    denom = grouped["rows"].replace(0, np.nan)
    grouped["sell_pct"] = (grouped["sell_count"] / denom).fillna(0.0)
    grouped["hold_pct"] = (grouped["hold_count"] / denom).fillna(0.0)
    grouped["buy_pct"] = (grouped["buy_count"] / denom).fillna(0.0)
    grouped["minority_pct"] = grouped["sell_pct"] + grouped["buy_pct"]

    if group_cols:
        return grouped.reset_index()
    return grouped.reset_index(drop=True)


def _distribution_payload(df: pd.DataFrame, hold_lower: float, hold_upper: float) -> dict[str, Any]:
    overall = _distribution_table(df, group_cols=[])
    by_timeframe = _distribution_table(df, group_cols=["timeframe"])
    by_symbol_timeframe = _distribution_table(df, group_cols=["timeframe", "symbol"])

    if overall.empty:
        overall_payload: dict[str, Any] = {
            "rows": 0,
            "class_counts": {"SELL": 0, "HOLD": 0, "BUY": 0},
            "class_pct": {"SELL": 0.0, "HOLD": 0.0, "BUY": 0.0},
            "minority_pct": 0.0,
            "within_hold_target_range": False,
        }
    else:
        row = overall.iloc[0]
        hold_pct = float(row["hold_pct"])
        overall_payload = {
            "rows": int(row["rows"]),
            "class_counts": {
                "SELL": int(row["sell_count"]),
                "HOLD": int(row["hold_count"]),
                "BUY": int(row["buy_count"]),
            },
            "class_pct": {
                "SELL": float(row["sell_pct"]),
                "HOLD": hold_pct,
                "BUY": float(row["buy_pct"]),
            },
            "minority_pct": float(row["minority_pct"]),
            "within_hold_target_range": bool(hold_lower <= hold_pct <= hold_upper),
        }

    if by_symbol_timeframe.empty:
        consistency_payload = {
            "group_count": 0,
            "groups_within_hold_target": 0,
            "groups_outside_hold_target": 0,
            "consistency_ratio": 0.0,
        }
    else:
        within_mask = by_symbol_timeframe["hold_pct"].between(hold_lower, hold_upper, inclusive="both")
        within_count = int(within_mask.sum())
        group_count = int(len(by_symbol_timeframe))
        consistency_payload = {
            "group_count": group_count,
            "groups_within_hold_target": within_count,
            "groups_outside_hold_target": int(group_count - within_count),
            "consistency_ratio": float(within_count / max(group_count, 1)),
        }

    return {
        "overall": overall_payload,
        "by_timeframe": by_timeframe.to_dict(orient="records"),
        "by_symbol_timeframe": by_symbol_timeframe.to_dict(orient="records"),
        "consistency": consistency_payload,
    }


def _evenly_spaced_sample(df: pd.DataFrame, n_rows: int) -> pd.DataFrame:
    if n_rows <= 0:
        return df.iloc[0:0].copy()
    if n_rows >= len(df):
        return df.copy()

    raw_indices = np.rint(np.linspace(0, len(df) - 1, n_rows)).astype(int)
    selected: list[int] = []
    seen: set[int] = set()

    for idx in raw_indices.tolist():
        if idx not in seen:
            selected.append(idx)
            seen.add(idx)

    if len(selected) < n_rows:
        for idx in range(len(df)):
            if idx not in seen:
                selected.append(idx)
                seen.add(idx)
            if len(selected) == n_rows:
                break

    selected = sorted(selected[:n_rows])
    return df.iloc[selected].copy()


def _allocate_extras(class_counts: dict[int, int], total_extra: int) -> dict[int, int]:
    if total_extra <= 0:
        return {key: 0 for key in class_counts}

    present = {cls: cnt for cls, cnt in class_counts.items() if cnt > 0}
    if not present:
        return {key: 0 for key in class_counts}

    weights = {cls: (1.0 / max(cnt, 1)) for cls, cnt in present.items()}
    weight_sum = sum(weights.values())

    raw = {cls: (total_extra * (weights[cls] / weight_sum)) for cls in present}
    base = {cls: int(np.floor(raw_val)) for cls, raw_val in raw.items()}
    assigned = sum(base.values())
    remaining = int(total_extra - assigned)

    if remaining > 0:
        fractions = sorted(
            ((cls, raw[cls] - base[cls]) for cls in present),
            key=lambda item: item[1],
            reverse=True,
        )
        for idx in range(remaining):
            target_cls = fractions[idx % len(fractions)][0]
            base[target_cls] += 1

    out = {key: 0 for key in class_counts}
    for cls, val in base.items():
        out[cls] = int(val)
    return out


def _numeric_feature_columns(df: pd.DataFrame) -> list[str]:
    excluded = {
        "target_class",
        "synthetic_balance",
        "balance_source",
    }
    numeric_cols = [col for col in df.columns if pd.api.types.is_numeric_dtype(df[col])]
    return [col for col in numeric_cols if col not in excluded]


def _generate_synthetic_rows(
    class_df: pd.DataFrame,
    class_label: int,
    n_samples: int,
    feature_columns: list[str],
    method: str,
    rng: np.random.Generator,
) -> pd.DataFrame:
    if n_samples <= 0 or class_df.empty:
        return class_df.iloc[0:0].copy()

    ordered = class_df.sort_values("timestamp").reset_index(drop=True)
    samples: list[pd.Series] = []
    per_anchor_offsets: dict[int, int] = {}

    for _ in range(n_samples):
        use_temporal_smote = method in {"temporal_smote", "smote"} and len(ordered) >= 2

        if use_temporal_smote:
            anchor_idx = int(rng.integers(1, len(ordered)))
            neighbor_left = max(0, anchor_idx - 5)
            neighbor_idx = int(rng.integers(neighbor_left, anchor_idx))

            anchor = ordered.iloc[anchor_idx].copy()
            neighbor = ordered.iloc[neighbor_idx].copy()
            alpha = float(rng.random())

            synthetic = anchor.copy()
            for col in feature_columns:
                anchor_val = pd.to_numeric(anchor.get(col), errors="coerce")
                neighbor_val = pd.to_numeric(neighbor.get(col), errors="coerce")
                if np.isfinite(anchor_val) and np.isfinite(neighbor_val):
                    synthetic[col] = float(anchor_val + alpha * (neighbor_val - anchor_val))
        else:
            anchor_idx = int(rng.integers(0, len(ordered)))
            anchor = ordered.iloc[anchor_idx].copy()
            synthetic = anchor.copy()

        base_ts = pd.to_datetime(synthetic["timestamp"], errors="coerce")
        if pd.isna(base_ts):
            continue

        per_anchor_offsets[anchor_idx] = per_anchor_offsets.get(anchor_idx, 0) + 1
        synthetic["timestamp"] = base_ts + pd.to_timedelta(per_anchor_offsets[anchor_idx], unit="us")

        synthetic["target_class"] = int(class_label)
        if "target_signal" in synthetic.index:
            synthetic["target_signal"] = CLASS_TO_LABEL[int(class_label)]
        if "tb_event" in synthetic.index:
            synthetic["tb_event"] = "synthetic_balance"
        synthetic["synthetic_balance"] = 1
        synthetic["balance_source"] = method if use_temporal_smote else "bootstrap"
        samples.append(synthetic)

    if not samples:
        return ordered.iloc[0:0].copy()

    return pd.DataFrame(samples)


def _balance_group(
    group: pd.DataFrame,
    target_hold_ratio: float,
    oversample_method: str,
    rng: np.random.Generator,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    ordered = group.sort_values("timestamp").reset_index(drop=True).copy()
    if "synthetic_balance" not in ordered.columns:
        ordered["synthetic_balance"] = 0
    if "balance_source" not in ordered.columns:
        ordered["balance_source"] = "original"

    timeframe = str(ordered["timeframe"].iloc[0])
    symbol = str(ordered["symbol"].iloc[0])

    hold_df = ordered[ordered["target_class"] == 0].copy()
    sell_df = ordered[ordered["target_class"] == -1].copy()
    buy_df = ordered[ordered["target_class"] == 1].copy()

    hold_count = int(len(hold_df))
    sell_count = int(len(sell_df))
    buy_count = int(len(buy_df))
    minority_count = int(sell_count + buy_count)
    original_rows = int(len(ordered))

    stats: dict[str, Any] = {
        "timeframe": timeframe,
        "symbol": symbol,
        "original_rows": original_rows,
        "original_counts": {
            "SELL": sell_count,
            "HOLD": hold_count,
            "BUY": buy_count,
        },
    }

    if original_rows == 0:
        stats["status"] = "empty"
        return ordered, stats

    if minority_count == 0:
        stats["status"] = "skipped_no_minority"
        stats["balanced_rows"] = original_rows
        stats["balanced_counts"] = stats["original_counts"]
        return ordered, stats

    target_hold = int(round(original_rows * float(target_hold_ratio)))
    target_hold = max(0, min(target_hold, hold_count))

    hold_kept = _evenly_spaced_sample(hold_df, target_hold)

    minority_target_total = int(max(0, original_rows - len(hold_kept)))
    additional_needed = int(max(0, minority_target_total - minority_count))

    extras = _allocate_extras(
        class_counts={-1: sell_count, 1: buy_count},
        total_extra=additional_needed,
    )

    feature_columns = _numeric_feature_columns(ordered)

    sell_synthetic = _generate_synthetic_rows(
        class_df=sell_df,
        class_label=-1,
        n_samples=int(extras.get(-1, 0)),
        feature_columns=feature_columns,
        method=oversample_method,
        rng=rng,
    )
    buy_synthetic = _generate_synthetic_rows(
        class_df=buy_df,
        class_label=1,
        n_samples=int(extras.get(1, 0)),
        feature_columns=feature_columns,
        method=oversample_method,
        rng=rng,
    )

    balanced = pd.concat(
        [
            hold_kept,
            sell_df,
            buy_df,
            sell_synthetic,
            buy_synthetic,
        ],
        ignore_index=True,
    )

    # Keep deterministic order without any random global shuffle.
    balanced = balanced.sort_values("timestamp").reset_index(drop=True)

    if len(balanced) > original_rows:
        balanced = balanced.iloc[:original_rows].copy()

    if len(balanced) < original_rows:
        shortfall = int(original_rows - len(balanced))
        hold_fill = _generate_synthetic_rows(
            class_df=hold_df,
            class_label=0,
            n_samples=shortfall,
            feature_columns=feature_columns,
            method="bootstrap",
            rng=rng,
        )
        balanced = pd.concat([balanced, hold_fill], ignore_index=True)
        balanced = balanced.sort_values("timestamp").reset_index(drop=True)
        if len(balanced) > original_rows:
            balanced = balanced.iloc[:original_rows].copy()

    counts_after = balanced["target_class"].value_counts().to_dict()
    stats["status"] = "balanced"
    stats["balanced_rows"] = int(len(balanced))
    stats["balanced_counts"] = {
        "SELL": int(counts_after.get(-1, 0)),
        "HOLD": int(counts_after.get(0, 0)),
        "BUY": int(counts_after.get(1, 0)),
    }
    stats["hold_downsampled"] = int(max(0, hold_count - len(hold_kept)))
    stats["sell_oversampled"] = int(len(sell_synthetic))
    stats["buy_oversampled"] = int(len(buy_synthetic))
    return balanced, stats


def _build_before_after_comparison(
    before_df: pd.DataFrame,
    after_df: pd.DataFrame,
    hold_lower: float,
    hold_upper: float,
) -> pd.DataFrame:
    before_groups = _distribution_table(before_df, group_cols=["timeframe", "symbol"]).copy()
    after_groups = _distribution_table(after_df, group_cols=["timeframe", "symbol"]).copy()

    if not before_groups.empty:
        before_groups["stage"] = "before"
    if not after_groups.empty:
        after_groups["stage"] = "after"

    combined = pd.concat([before_groups, after_groups], ignore_index=True)
    if combined.empty:
        combined["within_hold_target"] = pd.Series(dtype=bool)
        return combined

    combined["within_hold_target"] = combined["hold_pct"].between(hold_lower, hold_upper, inclusive="both")
    return combined.sort_values(["timeframe", "symbol", "stage"]).reset_index(drop=True)


def balance_dataset(config: BalanceConfig) -> dict[str, Any]:
    df = _load_labeled_dataset(config.input_path)
    rng = np.random.default_rng(int(config.random_state))

    split_active = (
        bool(config.balance_split_only)
        and config.split_column in df.columns
        and str(config.train_split_value).strip() != ""
    )

    if split_active:
        split_series = df[config.split_column].astype(str).str.lower().str.strip()
        train_token = str(config.train_split_value).strip().lower()
        balance_mask = split_series == train_token
        scope_df = df[balance_mask].copy()
        other_df = df[~balance_mask].copy()
    else:
        scope_df = df.copy()
        other_df = df.iloc[0:0].copy()

    scope_df = scope_df.sort_values(["timeframe", "symbol", "timestamp"]).reset_index(drop=True)

    before_scope_payload = _distribution_payload(
        scope_df,
        hold_lower=config.hold_ratio_lower,
        hold_upper=config.hold_ratio_upper,
    )

    balanced_groups: list[pd.DataFrame] = []
    group_stats: list[dict[str, Any]] = []

    for (_timeframe, _symbol), group in scope_df.groupby(["timeframe", "symbol"], sort=False):
        balanced_group, stats = _balance_group(
            group=group,
            target_hold_ratio=float(config.target_hold_ratio),
            oversample_method=str(config.oversample_method).strip().lower(),
            rng=rng,
        )
        balanced_groups.append(balanced_group)
        group_stats.append(stats)

    balanced_scope = (
        pd.concat(balanced_groups, ignore_index=True)
        if balanced_groups
        else scope_df.iloc[0:0].copy()
    )
    balanced_scope = balanced_scope.sort_values(["timeframe", "symbol", "timestamp"]).reset_index(drop=True)

    if config.include_unbalanced_rows_in_output and not other_df.empty:
        output_df = pd.concat([balanced_scope, other_df], ignore_index=True)
        output_df = output_df.sort_values(["timeframe", "symbol", "timestamp"]).reset_index(drop=True)
        output_scope = "balanced_split_plus_unbalanced_remainder"
    else:
        output_df = balanced_scope.copy()
        output_scope = "balanced_scope_only"

    after_scope_payload = _distribution_payload(
        balanced_scope,
        hold_lower=config.hold_ratio_lower,
        hold_upper=config.hold_ratio_upper,
    )
    after_output_payload = _distribution_payload(
        output_df,
        hold_lower=config.hold_ratio_lower,
        hold_upper=config.hold_ratio_upper,
    )

    comparison_df = _build_before_after_comparison(
        before_df=scope_df,
        after_df=balanced_scope,
        hold_lower=config.hold_ratio_lower,
        hold_upper=config.hold_ratio_upper,
    )

    config.output_path.parent.mkdir(parents=True, exist_ok=True)
    config.report_path.parent.mkdir(parents=True, exist_ok=True)
    config.comparison_path.parent.mkdir(parents=True, exist_ok=True)

    output_df.to_csv(config.output_path, index=False)
    comparison_df.to_csv(config.comparison_path, index=False)

    balanced_status_counts = pd.Series([stat.get("status", "unknown") for stat in group_stats]).value_counts().to_dict()

    report = {
        "input_path": str(config.input_path),
        "output_path": str(config.output_path),
        "report_path": str(config.report_path),
        "comparison_path": str(config.comparison_path),
        "scope": {
            "split_active": bool(split_active),
            "split_column": config.split_column,
            "train_split_value": config.train_split_value,
            "include_unbalanced_rows_in_output": bool(config.include_unbalanced_rows_in_output),
            "output_scope": output_scope,
            "scope_rows_before": int(len(scope_df)),
            "scope_rows_after": int(len(balanced_scope)),
            "output_rows_after": int(len(output_df)),
            "other_rows_excluded_or_untouched": int(len(other_df)),
        },
        "targets": {
            "target_hold_ratio": float(config.target_hold_ratio),
            "target_hold_range": [float(config.hold_ratio_lower), float(config.hold_ratio_upper)],
            "target_minority_range": [
                float(1.0 - config.hold_ratio_upper),
                float(1.0 - config.hold_ratio_lower),
            ],
        },
        "before": {
            "scope": before_scope_payload,
        },
        "after": {
            "scope": after_scope_payload,
            "output": after_output_payload,
        },
        "group_status": {
            "total_groups": int(len(group_stats)),
            "status_counts": {str(k): int(v) for k, v in balanced_status_counts.items()},
            "details": group_stats,
        },
    }

    with config.report_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_native(report), fp, indent=2)

    return report


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(
        description=(
            "Balance labeled training datasets by downsampling HOLD and oversampling BUY/SELL "
            "without shuffling chronology."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=root / "data" / "processed" / "training_dataset.csv",
        help="Input labeled dataset CSV.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "data" / "processed" / "training_dataset_balanced.csv",
        help="Output balanced dataset CSV.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=root / "outputs" / "reports" / "class_balance_report.json",
        help="Path to write detailed class-distribution report JSON.",
    )
    parser.add_argument(
        "--comparison",
        type=Path,
        default=root / "outputs" / "reports" / "class_distribution_before_after.csv",
        help="Path to write before-vs-after per symbol/timeframe class distribution CSV.",
    )
    parser.add_argument(
        "--target-hold-ratio",
        type=float,
        default=0.55,
        help="Target HOLD ratio after balancing (default: 0.55).",
    )
    parser.add_argument(
        "--hold-lower",
        type=float,
        default=0.50,
        help="Lower bound for acceptable HOLD ratio in reports (default: 0.50).",
    )
    parser.add_argument(
        "--hold-upper",
        type=float,
        default=0.60,
        help="Upper bound for acceptable HOLD ratio in reports (default: 0.60).",
    )
    parser.add_argument(
        "--oversample-method",
        type=str,
        default="temporal_smote",
        choices=["temporal_smote", "smote", "bootstrap"],
        help="Minority oversampling strategy (default: temporal_smote).",
    )
    parser.add_argument(
        "--disable-split-scope",
        action="store_true",
        help="Balance all rows (do not restrict to split=train).",
    )
    parser.add_argument(
        "--split-column",
        type=str,
        default="split",
        help="Split column name used to scope balancing (default: split).",
    )
    parser.add_argument(
        "--train-split-value",
        type=str,
        default="train",
        help="Split value considered train for balancing scope (default: train).",
    )
    parser.add_argument(
        "--include-unbalanced-rows",
        action="store_true",
        help="Append untouched rows outside balancing scope to output dataset.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Random seed for deterministic oversampling.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    report_payload = balance_dataset(
        BalanceConfig(
            input_path=args.input,
            output_path=args.output,
            report_path=args.report,
            comparison_path=args.comparison,
            target_hold_ratio=float(args.target_hold_ratio),
            hold_ratio_lower=float(args.hold_lower),
            hold_ratio_upper=float(args.hold_upper),
            balance_split_only=not bool(args.disable_split_scope),
            split_column=args.split_column,
            train_split_value=args.train_split_value,
            include_unbalanced_rows_in_output=bool(args.include_unbalanced_rows),
            oversample_method=str(args.oversample_method).strip().lower(),
            random_state=int(args.random_state),
        )
    )

    print(json.dumps(report_payload["after"]["scope"]["overall"], indent=2))