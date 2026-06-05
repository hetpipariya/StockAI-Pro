from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from experiments_v2.fusion.fusion_labeling import (
    CLASS_TO_LABEL,
    TripleBarrierConfig,
    generate_triple_barrier_targets,
)


@dataclass
class LabelImpactConfig:
    input_path: Path
    output_dataset_path: Path
    output_report_path: Path
    output_distribution_path: Path
    old_up_threshold: float = 0.015
    old_down_threshold: float = 0.015
    weak_move_pct: float = 0.0025
    tb_config: TripleBarrierConfig = TripleBarrierConfig()


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _time_limit_for_timeframe(timeframe: str, config: TripleBarrierConfig) -> int:
    token = str(timeframe).strip().lower()
    if token == "1m":
        return int(config.time_limit_1m)
    if token == "5m":
        return int(config.time_limit_5m)
    if token == "1h":
        return int(config.time_limit_1h)

    match = re.fullmatch(r"(\d+)([mh])", token)
    if not match:
        return int(config.default_time_limit)

    value = max(1, int(match.group(1)))
    unit = match.group(2)
    minutes = value * 60 if unit == "h" else value
    return max(1, int(round(240 / minutes)))


def _load_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    required = {"timestamp", "symbol", "timeframe", "open", "high", "low", "close"}
    optional = {
        "volume",
        "source_file",
        "split",
        "wf_fold",
        "atr_14",
        "realized_vol_20",
        "volatility",
    }

    frame = pd.read_csv(
        path,
        low_memory=False,
        usecols=lambda col: str(col) in (required | optional),
    )

    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Input file missing required columns: {missing}")

    out = frame.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out["symbol"] = out["symbol"].astype(str).str.upper().str.strip()
    out["timeframe"] = out["timeframe"].astype(str).str.lower().str.strip()

    for col in ["open", "high", "low", "close", "volume", "atr_14", "realized_vol_20", "volatility"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["timestamp", "symbol", "timeframe", "open", "high", "low", "close"]).copy()
    out = out.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    return out


def _generate_strict_labels(
    df: pd.DataFrame,
    config: TripleBarrierConfig,
    up_threshold: float,
    down_threshold: float,
) -> pd.DataFrame:
    blocks: list[pd.DataFrame] = []

    for (_symbol, timeframe), group in df.groupby(["symbol", "timeframe"], sort=False):
        g = group.sort_values("timestamp").reset_index(drop=True).copy()
        steps = _time_limit_for_timeframe(str(timeframe), config=config)

        future_close = pd.to_numeric(g["close"], errors="coerce").shift(-int(steps))
        future_return = (future_close / g["close"].replace(0.0, np.nan)) - 1.0

        strict_class = np.select(
            [future_return >= float(up_threshold), future_return <= -float(down_threshold)],
            [1, -1],
            default=0,
        ).astype(int)

        g["old_time_steps"] = int(steps)
        g["old_future_return"] = future_return
        g["old_target_class"] = strict_class
        g["old_target_signal"] = pd.Series(strict_class, index=g.index).map(CLASS_TO_LABEL)

        g = g.dropna(subset=["old_future_return"]).copy()
        if not g.empty:
            blocks.append(g)

    if not blocks:
        return df.iloc[0:0].copy()

    out = pd.concat(blocks, ignore_index=True)
    out = out.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    return out


def _class_distribution(df: pd.DataFrame, class_col: str, prefix: str) -> dict[str, Any]:
    counts = pd.to_numeric(df[class_col], errors="coerce").fillna(0).astype(int).value_counts().to_dict()
    sell = int(counts.get(-1, 0))
    hold = int(counts.get(0, 0))
    buy = int(counts.get(1, 0))
    rows = int(sell + hold + buy)
    denom = max(rows, 1)

    return {
        f"{prefix}_rows": rows,
        f"{prefix}_counts": {"SELL": sell, "HOLD": hold, "BUY": buy},
        f"{prefix}_pct": {
            "SELL": float(sell / denom),
            "HOLD": float(hold / denom),
            "BUY": float(buy / denom),
        },
        f"{prefix}_minority_pct": float((sell + buy) / denom),
    }


def _distribution_table(df: pd.DataFrame, class_col: str, stage: str) -> pd.DataFrame:
    grouped = (
        df.groupby(["timeframe", "symbol", class_col], observed=True)
        .size()
        .unstack(fill_value=0)
        .rename(columns={-1: "sell_count", 0: "hold_count", 1: "buy_count"})
        .reset_index()
    )

    for col in ["sell_count", "hold_count", "buy_count"]:
        if col not in grouped.columns:
            grouped[col] = 0

    grouped["rows"] = grouped[["sell_count", "hold_count", "buy_count"]].sum(axis=1)
    denom = grouped["rows"].replace(0, np.nan)
    grouped["sell_pct"] = (grouped["sell_count"] / denom).fillna(0.0)
    grouped["hold_pct"] = (grouped["hold_count"] / denom).fillna(0.0)
    grouped["buy_pct"] = (grouped["buy_count"] / denom).fillna(0.0)
    grouped["minority_pct"] = grouped["sell_pct"] + grouped["buy_pct"]
    grouped["stage"] = stage
    return grouped


def _directional_quality_metrics(
    frame: pd.DataFrame,
    label_col: str,
    return_col: str,
    weak_move_pct: float,
) -> dict[str, Any]:
    labels = pd.to_numeric(frame[label_col], errors="coerce").fillna(0).astype(int)
    returns = pd.to_numeric(frame[return_col], errors="coerce")

    directional_mask = labels != 0
    directional_rows = int(directional_mask.sum())

    if directional_rows == 0:
        return {
            "directional_rows": 0,
            "directional_accuracy": 0.0,
            "weak_move_rate": 0.0,
            "mean_abs_return_directional": 0.0,
        }

    label_sign = np.sign(labels[directional_mask].to_numpy(dtype=float))
    realized_sign = np.sign(returns[directional_mask].to_numpy(dtype=float))

    directional_accuracy = float(np.mean(label_sign == realized_sign))
    abs_ret = np.abs(returns[directional_mask].to_numpy(dtype=float))
    weak_rate = float(np.mean(abs_ret < float(weak_move_pct)))
    mean_abs_return = float(np.nanmean(abs_ret)) if len(abs_ret) else 0.0

    return {
        "directional_rows": directional_rows,
        "directional_accuracy": directional_accuracy,
        "weak_move_rate": weak_rate,
        "mean_abs_return_directional": mean_abs_return,
    }


def run_label_impact_analysis(config: LabelImpactConfig) -> dict[str, Any]:
    base = _load_frame(config.input_path)

    old_labeled = _generate_strict_labels(
        df=base,
        config=config.tb_config,
        up_threshold=float(config.old_up_threshold),
        down_threshold=float(config.old_down_threshold),
    )

    new_labeled = generate_triple_barrier_targets(df=base, config=config.tb_config)

    key_cols = ["timestamp", "symbol", "timeframe"]
    merge_cols_new = [
        *key_cols,
        "target_class",
        "target_signal",
        "label_method",
        "tb_profit_barrier",
        "tb_stop_barrier",
        "tb_up_return_pct",
        "tb_down_return_pct",
        "tb_regime_scale",
        "tb_time_steps",
        "tb_event",
    ]

    available_new_cols = [col for col in merge_cols_new if col in new_labeled.columns]
    merged = old_labeled.merge(
        new_labeled[available_new_cols],
        on=key_cols,
        how="inner",
        suffixes=("_old", "_new"),
    )

    merged = merged.sort_values(["symbol", "timeframe", "timestamp"]).reset_index(drop=True)
    merged["label_changed"] = merged["old_target_class"] != merged["target_class"]

    config.output_dataset_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_report_path.parent.mkdir(parents=True, exist_ok=True)
    config.output_distribution_path.parent.mkdir(parents=True, exist_ok=True)

    merged.to_csv(config.output_dataset_path, index=False)

    overall_old = _class_distribution(merged, class_col="old_target_class", prefix="old")
    overall_new = _class_distribution(merged, class_col="target_class", prefix="new")

    old_directional = int((merged["old_target_class"] != 0).sum())
    new_directional = int((merged["target_class"] != 0).sum())
    directional_uplift_abs = int(new_directional - old_directional)
    directional_uplift_rel = float((new_directional / max(old_directional, 1)) - 1.0)

    hold_old = int((merged["old_target_class"] == 0).sum())
    hold_new = int((merged["target_class"] == 0).sum())

    agreement_rate = float(np.mean((merged["old_target_class"] == merged["target_class"]).to_numpy(dtype=bool)))

    quality_old = _directional_quality_metrics(
        frame=merged,
        label_col="old_target_class",
        return_col="old_future_return",
        weak_move_pct=float(config.weak_move_pct),
    )
    quality_new = _directional_quality_metrics(
        frame=merged,
        label_col="target_class",
        return_col="old_future_return",
        weak_move_pct=float(config.weak_move_pct),
    )

    per_tf_rows: list[dict[str, Any]] = []
    for timeframe, tf_group in merged.groupby("timeframe", sort=False):
        tf_old = _class_distribution(tf_group, class_col="old_target_class", prefix="old")
        tf_new = _class_distribution(tf_group, class_col="target_class", prefix="new")
        tf_quality_old = _directional_quality_metrics(
            frame=tf_group,
            label_col="old_target_class",
            return_col="old_future_return",
            weak_move_pct=float(config.weak_move_pct),
        )
        tf_quality_new = _directional_quality_metrics(
            frame=tf_group,
            label_col="target_class",
            return_col="old_future_return",
            weak_move_pct=float(config.weak_move_pct),
        )

        per_tf_rows.append(
            {
                "timeframe": str(timeframe),
                **tf_old,
                **tf_new,
                "directional_uplift_abs": int((tf_group["target_class"] != 0).sum() - (tf_group["old_target_class"] != 0).sum()),
                "hold_reduction_abs": int((tf_group["old_target_class"] == 0).sum() - (tf_group["target_class"] == 0).sum()),
                "agreement_rate": float(np.mean((tf_group["old_target_class"] == tf_group["target_class"]).to_numpy(dtype=bool))),
                "quality_old": tf_quality_old,
                "quality_new": tf_quality_new,
            }
        )

    old_dist_table = _distribution_table(merged, class_col="old_target_class", stage="old")
    new_dist_table = _distribution_table(merged, class_col="target_class", stage="new")
    distribution_table = pd.concat([old_dist_table, new_dist_table], ignore_index=True)
    distribution_table = distribution_table.sort_values(["timeframe", "symbol", "stage"]).reset_index(drop=True)
    distribution_table.to_csv(config.output_distribution_path, index=False)

    report = {
        "input_path": str(config.input_path),
        "output_dataset_path": str(config.output_dataset_path),
        "output_report_path": str(config.output_report_path),
        "output_distribution_path": str(config.output_distribution_path),
        "rows_compared": int(len(merged)),
        "old_labeling": {
            "method": "strict_fixed_return_threshold",
            "up_threshold": float(config.old_up_threshold),
            "down_threshold": float(config.old_down_threshold),
            **overall_old,
        },
        "new_labeling": {
            "method": "dynamic_triple_barrier",
            "tb_config": {
                "profit_atr_mult": float(config.tb_config.profit_atr_mult),
                "stop_atr_mult": float(config.tb_config.stop_atr_mult),
                "min_barrier_pct": float(config.tb_config.min_barrier_pct),
                "max_barrier_pct": float(config.tb_config.max_barrier_pct),
                "volatility_column": str(config.tb_config.volatility_column),
                "volatility_lookback": int(config.tb_config.volatility_lookback),
                "volatility_floor_scale": float(config.tb_config.volatility_floor_scale),
                "volatility_cap_scale": float(config.tb_config.volatility_cap_scale),
                "time_limit_1m": int(config.tb_config.time_limit_1m),
                "time_limit_5m": int(config.tb_config.time_limit_5m),
                "time_limit_1h": int(config.tb_config.time_limit_1h),
            },
            **overall_new,
        },
        "impact": {
            "directional_uplift_abs": directional_uplift_abs,
            "directional_uplift_rel": directional_uplift_rel,
            "hold_reduction_abs": int(hold_old - hold_new),
            "agreement_rate": agreement_rate,
            "labels_changed_rows": int(merged["label_changed"].sum()),
            "labels_changed_pct": float(merged["label_changed"].mean() if len(merged) else 0.0),
            "quality_old": quality_old,
            "quality_new": quality_new,
            "quality_delta": {
                "directional_accuracy_delta": float(quality_new["directional_accuracy"] - quality_old["directional_accuracy"]),
                "weak_move_rate_delta": float(quality_new["weak_move_rate"] - quality_old["weak_move_rate"]),
                "mean_abs_return_directional_delta": float(
                    quality_new["mean_abs_return_directional"] - quality_old["mean_abs_return_directional"]
                ),
            },
        },
        "per_timeframe": per_tf_rows,
    }

    with config.output_report_path.open("w", encoding="utf-8") as fp:
        json.dump(_to_native(report), fp, indent=2)

    return report


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="Compare strict fixed-threshold labels against dynamic triple-barrier labels."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=root / "data" / "processed" / "featured_ohlcv.csv",
        help="Input feature dataset containing timestamp/symbol/timeframe/OHLCV columns.",
    )
    parser.add_argument(
        "--output-dataset",
        type=Path,
        default=root / "data" / "processed" / "training_dataset_dynamic_tbm.csv",
        help="Output CSV containing new labels and old/new comparison columns.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        default=root / "outputs" / "reports" / "labeling_impact_report.json",
        help="Output JSON path for summary impact analysis.",
    )
    parser.add_argument(
        "--distribution-out",
        type=Path,
        default=root / "outputs" / "reports" / "labeling_distribution_old_vs_new.csv",
        help="Output CSV path for per symbol/timeframe class distribution comparison.",
    )
    parser.add_argument(
        "--old-up-threshold",
        type=float,
        default=0.015,
        help="Strict old BUY threshold as decimal (default: 0.015 = 1.5%).",
    )
    parser.add_argument(
        "--old-down-threshold",
        type=float,
        default=0.015,
        help="Strict old SELL threshold as decimal (default: 0.015 = 1.5%).",
    )
    parser.add_argument(
        "--weak-move-pct",
        type=float,
        default=0.0025,
        help="Absolute return threshold used for weak-move noise proxy.",
    )
    parser.add_argument(
        "--tb-profit-atr-mult",
        type=float,
        default=1.15,
        help="ATR multiple for upper barrier before volatility scaling.",
    )
    parser.add_argument(
        "--tb-stop-atr-mult",
        type=float,
        default=0.95,
        help="ATR multiple for lower barrier before volatility scaling.",
    )
    parser.add_argument(
        "--tb-min-barrier-pct",
        type=float,
        default=0.005,
        help="Minimum barrier percent as decimal (0.005 = 0.5%).",
    )
    parser.add_argument(
        "--tb-max-barrier-pct",
        type=float,
        default=0.010,
        help="Maximum barrier percent as decimal (0.010 = 1.0%).",
    )
    parser.add_argument(
        "--tb-volatility-column",
        type=str,
        default="realized_vol_20",
        help="Feature column used for volatility regime scaling.",
    )
    parser.add_argument(
        "--tb-volatility-lookback",
        type=int,
        default=64,
        help="Lookback window for volatility regime anchors.",
    )
    parser.add_argument(
        "--tb-volatility-floor-scale",
        type=float,
        default=0.60,
        help="Lower clip for volatility regime scale.",
    )
    parser.add_argument(
        "--tb-volatility-cap-scale",
        type=float,
        default=1.40,
        help="Upper clip for volatility regime scale.",
    )
    parser.add_argument(
        "--tb-time-limit-1m",
        type=int,
        default=30,
        help="Time barrier in bars for 1m timeframe.",
    )
    parser.add_argument(
        "--tb-time-limit-5m",
        type=int,
        default=12,
        help="Time barrier in bars for 5m timeframe.",
    )
    parser.add_argument(
        "--tb-time-limit-1h",
        type=int,
        default=4,
        help="Time barrier in bars for 1h timeframe.",
    )
    parser.add_argument(
        "--tb-default-time-limit",
        type=int,
        default=8,
        help="Fallback time barrier for unknown timeframe tokens.",
    )
    parser.add_argument(
        "--tb-neutral-band-atr-mult",
        type=float,
        default=0.20,
        help="ATR multiple for neutral band at time barrier.",
    )
    parser.add_argument(
        "--tb-neutral-band-min-pct",
        type=float,
        default=0.0015,
        help="Minimum neutral band percentage as decimal.",
    )
    parser.add_argument(
        "--tb-neutral-band-max-pct",
        type=float,
        default=0.0040,
        help="Maximum neutral band percentage as decimal.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run_label_impact_analysis(
        LabelImpactConfig(
            input_path=args.input,
            output_dataset_path=args.output_dataset,
            output_report_path=args.report_out,
            output_distribution_path=args.distribution_out,
            old_up_threshold=float(args.old_up_threshold),
            old_down_threshold=float(args.old_down_threshold),
            weak_move_pct=float(args.weak_move_pct),
            tb_config=TripleBarrierConfig(
                profit_atr_mult=float(args.tb_profit_atr_mult),
                stop_atr_mult=float(args.tb_stop_atr_mult),
                min_barrier_pct=float(args.tb_min_barrier_pct),
                max_barrier_pct=float(args.tb_max_barrier_pct),
                volatility_column=str(args.tb_volatility_column),
                volatility_lookback=int(args.tb_volatility_lookback),
                volatility_floor_scale=float(args.tb_volatility_floor_scale),
                volatility_cap_scale=float(args.tb_volatility_cap_scale),
                time_limit_1m=int(args.tb_time_limit_1m),
                time_limit_5m=int(args.tb_time_limit_5m),
                time_limit_1h=int(args.tb_time_limit_1h),
                default_time_limit=int(args.tb_default_time_limit),
                neutral_band_atr_mult=float(args.tb_neutral_band_atr_mult),
                neutral_band_min_pct=float(args.tb_neutral_band_min_pct),
                neutral_band_max_pct=float(args.tb_neutral_band_max_pct),
            ),
        )
    )
    print(json.dumps(result["impact"], indent=2))