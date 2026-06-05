from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from experiments_v2 import production_5m_trading_system as prod
except ImportError:
    import production_5m_trading_system as prod


CONFIDENCE_CANDIDATES = [0.60, 0.65, 0.70, 0.75, 0.80]
QUALITY_QUANTILES = [0.50, 0.60, 0.70]


@dataclass
class Position:
    symbol: str
    side: int  # 1=BUY, -1=SELL
    entry_time: pd.Timestamp
    entry_price: float
    quantity: int
    stop_price: float
    target_price: float
    bars_held: int = 0


def _to_native(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_native(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_native(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


def _compute_series_by_symbol_ffill(
    frame: pd.DataFrame,
    base_series: pd.Series,
) -> pd.Series:
    out = pd.to_numeric(base_series, errors="coerce").replace([np.inf, -np.inf], np.nan)
    out.index = frame.index
    out = out.groupby(frame["symbol"], sort=False).ffill().fillna(0.0)
    return out.astype(np.float64)


def _resolve_quality_features(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series, dict[str, str]]:
    source: dict[str, str] = {}

    if "trend_strength" in frame.columns:
        trend_strength = _compute_series_by_symbol_ffill(frame, frame["trend_strength"])
        source["trend_strength"] = "trend_strength"
    elif "ema_20" in frame.columns:
        ema20 = _compute_series_by_symbol_ffill(frame, frame["ema_20"])
        close = _compute_series_by_symbol_ffill(frame, frame["close"])
        trend_strength = (close - ema20) / np.maximum(np.abs(ema20), 1e-12)
        source["trend_strength"] = "derived_from_close_ema20"
    else:
        close = _compute_series_by_symbol_ffill(frame, frame["close"])
        momentum = close.groupby(frame["symbol"], sort=False).pct_change(10).fillna(0.0)
        trend_strength = momentum.astype(np.float64)
        source["trend_strength"] = "derived_from_10bar_momentum"

    if "volatility" in frame.columns:
        volatility = _compute_series_by_symbol_ffill(frame, frame["volatility"])
        source["volatility"] = "volatility"
    elif "realized_vol_20" in frame.columns:
        volatility = _compute_series_by_symbol_ffill(frame, frame["realized_vol_20"])
        source["volatility"] = "realized_vol_20"
    elif "atr_pct" in frame.columns:
        volatility = _compute_series_by_symbol_ffill(frame, frame["atr_pct"])
        source["volatility"] = "atr_pct"
    else:
        close = _compute_series_by_symbol_ffill(frame, frame["close"])
        pct = close.groupby(frame["symbol"], sort=False).pct_change().fillna(0.0)
        volatility = (
            pct.groupby(frame["symbol"], sort=False)
            .rolling(20, min_periods=20)
            .std()
            .reset_index(level=0, drop=True)
            .fillna(0.0)
        )
        source["volatility"] = "derived_from_rolling_return_std"

    trend_strength = trend_strength.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    volatility = volatility.replace([np.inf, -np.inf], 0.0).fillna(0.0)
    return trend_strength.astype(np.float64), volatility.astype(np.float64), source


def _thresholds_from_quantiles(
    trend_strength: pd.Series,
    volatility: pd.Series,
) -> tuple[list[float], list[float]]:
    trend_abs = trend_strength.abs().replace([np.inf, -np.inf], np.nan).dropna()
    vol_abs = volatility.abs().replace([np.inf, -np.inf], np.nan).dropna()

    if trend_abs.empty:
        trend_abs = pd.Series([0.0], dtype=np.float64)
    if vol_abs.empty:
        vol_abs = pd.Series([0.0], dtype=np.float64)

    trend_thresholds = sorted(
        {
            float(max(0.0, trend_abs.quantile(q)))
            for q in QUALITY_QUANTILES
        }
    )
    vol_thresholds = sorted(
        {
            float(max(0.0, vol_abs.quantile(q)))
            for q in QUALITY_QUANTILES
        }
    )

    return trend_thresholds, vol_thresholds


def _trade_pnl(side: int, entry: float, exit_price: float, qty: int) -> float:
    if side == 1:
        return float((exit_price - entry) * qty)
    return float((entry - exit_price) * qty)


def _run_backtest_with_quality(
    frame: pd.DataFrame,
    pred: np.ndarray,
    confidence: np.ndarray,
    trend_strength: pd.Series,
    volatility: pd.Series,
    *,
    starting_capital: float,
    risk_per_trade_pct: float,
    max_concurrent_trades: int,
    confidence_threshold: float,
    trend_threshold: float,
    volatility_threshold: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
    daily_loss_limit_pct: float,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    work["pred"] = pred.astype(np.int32)
    work["confidence"] = confidence.astype(np.float32)
    work["trend_strength_q"] = trend_strength.to_numpy(dtype=np.float64)
    work["volatility_q"] = volatility.to_numpy(dtype=np.float64)
    work["date"] = work["timestamp"].dt.date

    open_positions: dict[str, Position] = {}
    trade_rows: list[dict[str, Any]] = []

    capital = float(starting_capital)
    peak_capital = float(starting_capital)
    current_day: Any = None
    day_start_capital = float(starting_capital)
    halted_for_day = False

    confidence_pass = 0
    quality_rejected = 0
    sideways_filtered = 0
    risk_rejected = 0
    skipped_overlap = 0

    for row in work.itertuples(index=False):
        ts = pd.Timestamp(row.timestamp)
        symbol = str(row.symbol)
        close = float(row.close)
        high = float(row.high)
        low = float(row.low)

        if current_day != row.date:
            current_day = row.date
            day_start_capital = capital
            halted_for_day = False

        if day_start_capital > 0:
            daily_pnl_pct = (capital - day_start_capital) / day_start_capital
            if daily_pnl_pct <= -float(daily_loss_limit_pct):
                halted_for_day = True

        pos = open_positions.get(symbol)
        if pos is not None:
            pos.bars_held += 1
            exit_reason = None
            exit_price = None

            if pos.side == 1:
                hit_tp = high >= pos.target_price
                hit_sl = low <= pos.stop_price
                if hit_tp and hit_sl:
                    exit_reason = "STOP_LOSS_HIT"
                    exit_price = pos.stop_price
                elif hit_sl:
                    exit_reason = "STOP_LOSS_HIT"
                    exit_price = pos.stop_price
                elif hit_tp:
                    exit_reason = "TAKE_PROFIT_HIT"
                    exit_price = pos.target_price
            else:
                hit_tp = low <= pos.target_price
                hit_sl = high >= pos.stop_price
                if hit_tp and hit_sl:
                    exit_reason = "STOP_LOSS_HIT"
                    exit_price = pos.stop_price
                elif hit_sl:
                    exit_reason = "STOP_LOSS_HIT"
                    exit_price = pos.stop_price
                elif hit_tp:
                    exit_reason = "TAKE_PROFIT_HIT"
                    exit_price = pos.target_price

            if exit_reason is None and pos.bars_held >= int(max_holding_bars):
                exit_reason = "MAX_HOLD_EXIT"
                exit_price = close

            if exit_reason is not None and exit_price is not None:
                pnl = _trade_pnl(pos.side, pos.entry_price, float(exit_price), pos.quantity)
                capital += pnl
                peak_capital = max(peak_capital, capital)

                trade_rows.append(
                    {
                        "symbol": pos.symbol,
                        "side": "BUY" if pos.side == 1 else "SELL",
                        "entry_time": str(pos.entry_time),
                        "exit_time": str(ts),
                        "entry_price": float(pos.entry_price),
                        "exit_price": float(exit_price),
                        "quantity": int(pos.quantity),
                        "bars_held": int(pos.bars_held),
                        "exit_reason": str(exit_reason),
                        "pnl": float(pnl),
                        "capital_after": float(capital),
                    }
                )
                del open_positions[symbol]

        conf = float(row.confidence)
        if conf <= float(confidence_threshold):
            continue

        confidence_pass += 1
        side = 1 if int(row.pred) == 1 else -1

        tr = float(row.trend_strength_q)
        vol = float(row.volatility_q)

        regime = "trending" if (abs(tr) >= float(trend_threshold) and vol >= float(volatility_threshold)) else "sideways"
        if regime != "trending":
            sideways_filtered += 1
            quality_rejected += 1
            continue

        if side == 1 and tr < float(trend_threshold):
            quality_rejected += 1
            continue
        if side == -1 and tr > -float(trend_threshold):
            quality_rejected += 1
            continue

        if halted_for_day:
            risk_rejected += 1
            continue

        if symbol in open_positions:
            skipped_overlap += 1
            continue

        if len(open_positions) >= int(max_concurrent_trades):
            risk_rejected += 1
            continue

        if close <= 0:
            risk_rejected += 1
            continue

        stop_distance = close * float(stop_loss_pct)
        if stop_distance <= 0:
            risk_rejected += 1
            continue

        size_factor = prod._size_reduction_factor(capital, peak_capital)
        risk_budget = capital * float(risk_per_trade_pct) * size_factor
        qty = int(risk_budget / stop_distance)
        qty = min(qty, int(capital / close))
        if qty <= 0:
            risk_rejected += 1
            continue

        if side == 1:
            sl = close * (1.0 - float(stop_loss_pct))
            tp = close * (1.0 + float(take_profit_pct))
        else:
            sl = close * (1.0 + float(stop_loss_pct))
            tp = close * (1.0 - float(take_profit_pct))

        open_positions[symbol] = Position(
            symbol=symbol,
            side=side,
            entry_time=ts,
            entry_price=float(close),
            quantity=int(qty),
            stop_price=float(sl),
            target_price=float(tp),
        )

    trades_df = pd.DataFrame(trade_rows)
    if trades_df.empty:
        summary = {
            "total_profit": 0.0,
            "profit_factor": None,
            "max_drawdown": 0.0,
            "total_trades": 0,
            "win_rate": 0.0,
            "ending_capital": float(capital),
            "confidence_pass": int(confidence_pass),
            "quality_rejected": int(quality_rejected),
            "sideways_filtered": int(sideways_filtered),
            "risk_rejected": int(risk_rejected),
            "overlap_skipped": int(skipped_overlap),
        }
        daily_df = pd.DataFrame(
            columns=["date", "daily_pnl", "trades", "wins", "win_rate", "equity_close", "drawdown_pct"]
        )
        return summary, trades_df, daily_df

    trades_df["exit_time"] = pd.to_datetime(trades_df["exit_time"])
    trades_df = trades_df.sort_values("exit_time").reset_index(drop=True)
    trades_df["date"] = trades_df["exit_time"].dt.date.astype(str)
    trades_df["win"] = trades_df["pnl"] > 0

    wins = int(trades_df["win"].sum())
    total_trades = int(len(trades_df))
    win_rate = float(wins / max(total_trades, 1))

    gross_profit = float(trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum())
    gross_loss_abs = float(abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum()))
    profit_factor = float(gross_profit / gross_loss_abs) if gross_loss_abs > 0 else None

    equity_curve = float(starting_capital) + trades_df["pnl"].cumsum()
    running_peak = equity_curve.cummax()
    dd = (running_peak - equity_curve) / np.maximum(running_peak, 1e-12)
    max_drawdown = float(dd.max()) if len(dd) else 0.0

    daily_df = (
        trades_df.groupby("date", as_index=False)
        .agg(
            daily_pnl=("pnl", "sum"),
            trades=("pnl", "count"),
            wins=("win", "sum"),
            gross_profit=("pnl", lambda s: float(s[s > 0].sum())),
            gross_loss_abs=("pnl", lambda s: float(abs(s[s < 0].sum()))),
            equity_close=("capital_after", "last"),
        )
    )
    daily_df["win_rate"] = daily_df["wins"] / np.maximum(daily_df["trades"], 1)
    daily_df["profit_factor"] = np.where(
        daily_df["gross_loss_abs"] > 0,
        daily_df["gross_profit"] / daily_df["gross_loss_abs"],
        np.nan,
    )
    daily_df["peak_equity"] = daily_df["equity_close"].cummax()
    daily_df["drawdown_pct"] = (daily_df["peak_equity"] - daily_df["equity_close"]) / np.maximum(
        daily_df["peak_equity"], 1e-12
    )

    daily_pnl = pd.to_numeric(daily_df["daily_pnl"], errors="coerce").fillna(0.0)
    daily_sharpe = 0.0
    if len(daily_pnl) > 1 and float(daily_pnl.std(ddof=1)) > 1e-12:
        daily_sharpe = float((daily_pnl.mean() / daily_pnl.std(ddof=1)) * np.sqrt(252.0))

    summary = {
        "total_profit": float(trades_df["pnl"].sum()),
        "profit_factor": profit_factor,
        "max_drawdown": max_drawdown,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "ending_capital": float(capital),
        "confidence_pass": int(confidence_pass),
        "quality_rejected": int(quality_rejected),
        "sideways_filtered": int(sideways_filtered),
        "risk_rejected": int(risk_rejected),
        "overlap_skipped": int(skipped_overlap),
        "profitable_days_pct": float((daily_pnl > 0).mean()) if len(daily_pnl) else 0.0,
        "daily_sharpe": daily_sharpe,
    }
    return summary, trades_df, daily_df


def run_optimization(
    dataset_path: Path,
    model_path: Path,
    output_dir: Path,
    *,
    starting_capital: float,
    risk_per_trade_pct: float,
    max_concurrent_trades: int,
    stop_loss_pct: float,
    take_profit_pct: float,
    max_holding_bars: int,
    daily_loss_limit_pct: float,
) -> dict[str, Any]:
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

    trend_strength, volatility, quality_sources = _resolve_quality_features(frame_test)
    trend_thresholds, vol_thresholds = _thresholds_from_quantiles(trend_strength, volatility)

    comparison_rows: list[dict[str, Any]] = []
    detailed_runs: list[dict[str, Any]] = []

    for conf_th in CONFIDENCE_CANDIDATES:
        for trend_th in trend_thresholds:
            for vol_th in vol_thresholds:
                summary, trades_df, daily_df = _run_backtest_with_quality(
                    frame=frame_test,
                    pred=pred,
                    confidence=confidence,
                    trend_strength=trend_strength,
                    volatility=volatility,
                    starting_capital=starting_capital,
                    risk_per_trade_pct=risk_per_trade_pct,
                    max_concurrent_trades=max_concurrent_trades,
                    confidence_threshold=conf_th,
                    trend_threshold=trend_th,
                    volatility_threshold=vol_th,
                    stop_loss_pct=stop_loss_pct,
                    take_profit_pct=take_profit_pct,
                    max_holding_bars=max_holding_bars,
                    daily_loss_limit_pct=daily_loss_limit_pct,
                )

                goal_met = (
                    summary["profit_factor"] is not None
                    and float(summary["profit_factor"]) > 1.3
                )

                row = {
                    "confidence_threshold": float(conf_th),
                    "trend_threshold": float(trend_th),
                    "volatility_threshold": float(vol_th),
                    "total_profit": float(summary["total_profit"]),
                    "profit_factor": summary["profit_factor"],
                    "max_drawdown": float(summary["max_drawdown"]),
                    "total_trades": int(summary["total_trades"]),
                    "win_rate": float(summary["win_rate"]),
                    "profitable_days_pct": float(summary["profitable_days_pct"]),
                    "daily_sharpe": float(summary["daily_sharpe"]),
                    "quality_rejected": int(summary["quality_rejected"]),
                    "sideways_filtered": int(summary["sideways_filtered"]),
                    "goal_met_pf_gt_1_3": bool(goal_met),
                }
                comparison_rows.append(row)
                detailed_runs.append(
                    {
                        "config": {
                            "confidence_threshold": float(conf_th),
                            "trend_threshold": float(trend_th),
                            "volatility_threshold": float(vol_th),
                        },
                        "summary": summary,
                        "trades": trades_df,
                        "daily": daily_df,
                    }
                )

    comparison_df = pd.DataFrame(comparison_rows).sort_values(
        ["goal_met_pf_gt_1_3", "profit_factor", "max_drawdown", "daily_sharpe", "total_profit"],
        ascending=[False, False, True, False, False],
    )

    best_row = comparison_df.iloc[0]
    best_config = {
        "confidence_threshold": float(best_row["confidence_threshold"]),
        "trend_threshold": float(best_row["trend_threshold"]),
        "volatility_threshold": float(best_row["volatility_threshold"]),
    }

    best_run = next(
        run
        for run in detailed_runs
        if run["config"] == best_config
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    comparison_path = output_dir / "signal_quality_sweep_comparison.csv"
    report_path = output_dir / "signal_quality_sweep_report.json"
    best_trades_path = output_dir / "signal_quality_best_trades.csv"
    best_daily_path = output_dir / "signal_quality_best_daily.csv"

    comparison_df.to_csv(comparison_path, index=False)
    best_run["trades"].to_csv(best_trades_path, index=False)
    best_run["daily"].to_csv(best_daily_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "model": str(model_path),
        "goal": "Increase PF above 1.3 by improving signal quality",
        "quality_feature_sources": quality_sources,
        "sweeps": {
            "confidence_thresholds": CONFIDENCE_CANDIDATES,
            "trend_threshold_candidates": trend_thresholds,
            "volatility_threshold_candidates": vol_thresholds,
            "regime_definition": "TRENDING if abs(trend_strength) >= trend_threshold and volatility >= volatility_threshold; otherwise SIDEWAYS",
            "entry_rule": "Trade only in TRENDING regime with directional trend alignment",
        },
        "fixed_risk_config": {
            "risk_per_trade_pct": float(risk_per_trade_pct),
            "max_concurrent_trades": int(max_concurrent_trades),
            "stop_loss_pct": float(stop_loss_pct),
            "take_profit_pct": float(take_profit_pct),
            "max_holding_bars": int(max_holding_bars),
            "daily_loss_limit_pct": float(daily_loss_limit_pct),
            "drawdown_size_reduction": {
                "drawdown_gt_10pct": 0.50,
                "drawdown_gt_20pct": 0.25,
            },
        },
        "best_configuration": {
            **best_config,
            "metrics": {
                "total_profit": float(best_row["total_profit"]),
                "profit_factor": (
                    float(best_row["profit_factor"])
                    if pd.notna(best_row["profit_factor"])
                    else None
                ),
                "max_drawdown": float(best_row["max_drawdown"]),
                "total_trades": int(best_row["total_trades"]),
                "win_rate": float(best_row["win_rate"]),
                "profitable_days_pct": float(best_row["profitable_days_pct"]),
                "daily_sharpe": float(best_row["daily_sharpe"]),
            },
        },
        "goal_achieved_pf_gt_1_3": bool(best_row["goal_met_pf_gt_1_3"]),
        "top_5": _to_native(comparison_df.head(5).replace({np.nan: None}).to_dict(orient="records")),
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
        description="Optimize 5m trading edge via confidence and market regime quality filters"
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
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--max-concurrent-trades", type=int, default=3)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--take-profit-pct", type=float, default=0.015)
    parser.add_argument("--max-holding-bars", type=int, default=6)
    parser.add_argument("--daily-loss-limit-pct", type=float, default=0.03)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_optimization(
        dataset_path=args.dataset,
        model_path=args.model,
        output_dir=args.output_dir,
        starting_capital=args.starting_capital,
        risk_per_trade_pct=args.risk_per_trade_pct,
        max_concurrent_trades=args.max_concurrent_trades,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        max_holding_bars=args.max_holding_bars,
        daily_loss_limit_pct=args.daily_loss_limit_pct,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
