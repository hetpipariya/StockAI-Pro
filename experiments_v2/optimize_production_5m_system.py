from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from experiments_v2 import production_5m_trading_system as prod
except ImportError:
    import production_5m_trading_system as prod


RISK_PER_TRADE_CANDIDATES = [0.005, 0.01, 0.015]
DAILY_LOSS_LIMIT_CANDIDATES = [0.02, 0.03]


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _stability_metrics(daily_df: pd.DataFrame) -> dict[str, Any]:
    if daily_df.empty:
        return {
            "profitable_days_pct": 0.0,
            "daily_pnl_std": 0.0,
            "daily_sharpe": 0.0,
            "stability_score": 0.0,
        }

    daily_pnl = pd.to_numeric(daily_df["daily_pnl"], errors="coerce").fillna(0.0)
    profitable_days_pct = float((daily_pnl > 0).mean())
    daily_pnl_std = float(daily_pnl.std(ddof=0))
    std_for_sharpe = float(daily_pnl.std(ddof=1)) if len(daily_pnl) > 1 else 0.0

    if std_for_sharpe > 1e-12:
        daily_sharpe = float((daily_pnl.mean() / std_for_sharpe) * np.sqrt(252.0))
    else:
        daily_sharpe = 0.0

    # Bounded [0,1] consistency score from profitable-day ratio and Sharpe sign.
    sharpe_component = float(np.tanh(max(daily_sharpe, -3.0) / 3.0))
    stability_score = float(max(0.0, profitable_days_pct * (0.5 + 0.5 * sharpe_component)))

    return {
        "profitable_days_pct": profitable_days_pct,
        "daily_pnl_std": daily_pnl_std,
        "daily_sharpe": daily_sharpe,
        "stability_score": stability_score,
    }


def run_optimization(
    dataset_path: Path,
    model_path: Path,
    output_dir: Path,
    *,
    starting_capital: float,
    max_concurrent_trades: int,
    confidence_threshold: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    payload = prod._load_model_payload(model_path)
    model = payload["model"]
    feature_columns = list(payload["feature_columns"])

    df = pd.read_parquet(dataset_path)
    frame, X = prod._prepare_5m_data(df, feature_columns)

    split_idx = int(len(frame) * 0.8)
    split_idx = max(1, min(len(frame) - 1, split_idx))
    frame_test = frame.iloc[split_idx:].copy().reset_index(drop=True)
    X_test = X.iloc[split_idx:].copy().reset_index(drop=True)

    prob_buy = model.predict_proba(X_test)[:, 1].astype(np.float32)
    pred = (prob_buy >= 0.5).astype(np.int32)
    confidence = np.maximum(prob_buy, 1.0 - prob_buy).astype(np.float32)

    result_rows: list[dict[str, Any]] = []
    per_config_reports: list[dict[str, Any]] = []

    for risk_per_trade_pct in RISK_PER_TRADE_CANDIDATES:
        for daily_loss_limit_pct in DAILY_LOSS_LIMIT_CANDIDATES:
            summary, trades_df, daily_df = prod._run_backtest(
                frame=frame_test,
                pred=pred,
                confidence=confidence,
                starting_capital=starting_capital,
                risk_per_trade_pct=risk_per_trade_pct,
                max_concurrent_trades=max_concurrent_trades,
                confidence_threshold=confidence_threshold,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                daily_loss_limit_pct=daily_loss_limit_pct,
                max_holding_bars=max_holding_bars,
            )

            stability = _stability_metrics(daily_df)
            goal_met = (
                summary.get("profit_factor") is not None
                and float(summary["profit_factor"]) > 1.3
                and float(summary["max_drawdown"]) < 0.15
            )

            row = {
                "risk_per_trade_pct": float(risk_per_trade_pct),
                "daily_loss_limit_pct": float(daily_loss_limit_pct),
                "total_profit": float(summary["total_profit"]),
                "profit_factor": summary["profit_factor"],
                "max_drawdown": float(summary["max_drawdown"]),
                "win_rate": float(summary["win_rate"]),
                "total_trades": int(summary["total_trades"]),
                "signals_skipped": int(summary["signals_skipped"]),
                "signals_rejected_by_risk": int(summary["signals_rejected_by_risk"]),
                "profitable_days_pct": float(stability["profitable_days_pct"]),
                "daily_sharpe": float(stability["daily_sharpe"]),
                "daily_pnl_std": float(stability["daily_pnl_std"]),
                "stability_score": float(stability["stability_score"]),
                "goal_met": bool(goal_met),
            }
            result_rows.append(row)

            per_config_reports.append(
                {
                    "config": {
                        "risk_per_trade_pct": float(risk_per_trade_pct),
                        "daily_loss_limit_pct": float(daily_loss_limit_pct),
                    },
                    "summary": summary,
                    "stability": stability,
                    "trades": trades_df,
                    "daily": daily_df,
                    "goal_met": goal_met,
                }
            )

    results_df = pd.DataFrame(result_rows).sort_values(
        ["goal_met", "profit_factor", "max_drawdown", "stability_score", "total_profit"],
        ascending=[False, False, True, False, False],
    )

    valid_df = results_df[results_df["goal_met"]]
    if not valid_df.empty:
        best_row = valid_df.sort_values(
            ["total_profit", "stability_score", "profit_factor"],
            ascending=[False, False, False],
        ).iloc[0]
        selection_mode = "goal_constrained_best_profit"
    else:
        best_row = results_df.iloc[0]
        selection_mode = "best_available_pf_dd_stability"

    best_cfg = {
        "risk_per_trade_pct": float(best_row["risk_per_trade_pct"]),
        "daily_loss_limit_pct": float(best_row["daily_loss_limit_pct"]),
    }

    best_detail = next(
        r
        for r in per_config_reports
        if r["config"]["risk_per_trade_pct"] == best_cfg["risk_per_trade_pct"]
        and r["config"]["daily_loss_limit_pct"] == best_cfg["daily_loss_limit_pct"]
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "production_5m_optimization_comparison.csv"
    report_path = output_dir / "production_5m_optimization_report.json"
    best_trades_path = output_dir / "production_5m_optimization_best_trades.csv"
    best_daily_path = output_dir / "production_5m_optimization_best_daily.csv"

    results_df.to_csv(comparison_path, index=False)
    best_detail["trades"].to_csv(best_trades_path, index=False)
    best_detail["daily"].to_csv(best_daily_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "model": str(model_path),
        "goal": {
            "target_profit_factor_gt": 1.3,
            "target_max_drawdown_lt": 0.15,
        },
        "tested_parameters": {
            "risk_per_trade_pct": RISK_PER_TRADE_CANDIDATES,
            "daily_loss_limit_pct": DAILY_LOSS_LIMIT_CANDIDATES,
            "confidence_threshold_rule": f"> {confidence_threshold}",
            "drawdown_size_reduction": {
                "drawdown_gt_10pct": 0.50,
                "drawdown_gt_20pct": 0.25,
            },
            "max_concurrent_trades": int(max_concurrent_trades),
            "stop_loss_pct": float(stop_loss_pct),
            "take_profit_pct": float(take_profit_pct),
            "max_holding_bars": int(max_holding_bars),
        },
        "selection_mode": selection_mode,
        "goal_achieved": bool(best_row["goal_met"]),
        "best_configuration": {
            **best_cfg,
            "metrics": {
                "total_profit": float(best_row["total_profit"]),
                "profit_factor": (
                    float(best_row["profit_factor"])
                    if pd.notna(best_row["profit_factor"])
                    else None
                ),
                "max_drawdown": float(best_row["max_drawdown"]),
                "win_rate": float(best_row["win_rate"]),
                "stability_score": float(best_row["stability_score"]),
                "profitable_days_pct": float(best_row["profitable_days_pct"]),
                "daily_sharpe": float(best_row["daily_sharpe"]),
                "daily_pnl_std": float(best_row["daily_pnl_std"]),
            },
        },
        "top_3_configurations": _to_native(
            results_df.head(3).replace({np.nan: None}).to_dict(orient="records")
        ),
        "artifacts": {
            "comparison": str(comparison_path),
            "report": str(report_path),
            "best_trades": str(best_trades_path),
            "best_daily": str(best_daily_path),
        },
    }

    report_path.write_text(json.dumps(_to_native(report), indent=2), encoding="utf-8")
    return _to_native(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Optimize production 5m trading settings for profit factor and drawdown"
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("experiments_v2/data/combined_dataset.parquet"),
        help="Path to combined parquet dataset",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=Path("experiments_v2/outputs/models/5m_profit_model/xgb_5m_profit_model.joblib"),
        help="Path to trained 5m model payload",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("experiments_v2/outputs/reports"),
        help="Output directory",
    )
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--max-concurrent-trades", type=int, default=3)
    parser.add_argument("--confidence-threshold", type=float, default=0.60)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--take-profit-pct", type=float, default=0.015)
    parser.add_argument("--max-holding-bars", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_optimization(
        dataset_path=args.dataset,
        model_path=args.model,
        output_dir=args.output_dir,
        starting_capital=args.starting_capital,
        max_concurrent_trades=args.max_concurrent_trades,
        confidence_threshold=args.confidence_threshold,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        max_holding_bars=args.max_holding_bars,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
