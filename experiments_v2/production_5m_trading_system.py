from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd


TIMEFRAME = "5m"


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


def _load_model_payload(model_path: Path) -> dict[str, Any]:
    if not model_path.exists():
        raise FileNotFoundError(f"Model artifact not found: {model_path}")
    payload = joblib.load(model_path)
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected payload in {model_path}; expected dict")
    if "model" not in payload or "feature_columns" not in payload:
        raise RuntimeError(f"Model payload missing model/feature_columns in {model_path}")
    return payload


def _prepare_5m_data(df: pd.DataFrame, feature_columns: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = df[df["timeframe"].astype(str).str.lower() == TIMEFRAME].copy()
    if frame.empty:
        raise RuntimeError("No 5m rows found in dataset")

    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame["symbol"] = frame["symbol"].astype(str)
    frame = frame.dropna(subset=["timestamp", "symbol", "close", "high", "low"]).copy()

    for col in feature_columns:
        if col not in frame.columns:
            frame[col] = 0.0
        if pd.api.types.is_bool_dtype(frame[col]):
            frame[col] = frame[col].astype(np.int8)
        frame[col] = pd.to_numeric(frame[col], errors="coerce")

    frame = frame.dropna(subset=["close", "high", "low", *feature_columns]).copy()
    frame = frame.sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("No usable 5m rows after preprocessing")

    X = frame[feature_columns].copy()
    return frame, X


def _size_reduction_factor(current_capital: float, peak_capital: float) -> float:
    if peak_capital <= 0:
        return 1.0
    drawdown = max(0.0, (peak_capital - current_capital) / peak_capital)

    # Requested drawdown control:
    # >10% drawdown -> cut position size by 50%
    # >20% drawdown -> cut position size by 75%
    if drawdown > 0.20:
        return 0.25
    if drawdown > 0.10:
        return 0.50
    return 1.0


def _compute_trade_pnl(side: int, entry: float, exit_price: float, quantity: int) -> float:
    if side == 1:
        return float((exit_price - entry) * quantity)
    return float((entry - exit_price) * quantity)


def _run_backtest(
    frame: pd.DataFrame,
    pred: np.ndarray,
    confidence: np.ndarray,
    *,
    starting_capital: float,
    risk_per_trade_pct: float,
    max_concurrent_trades: int,
    confidence_threshold: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    daily_loss_limit_pct: float,
    max_holding_bars: int,
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    work["pred"] = pred.astype(np.int32)
    work["confidence"] = confidence.astype(np.float32)
    work["date"] = work["timestamp"].dt.date

    open_positions: dict[str, Position] = {}
    trade_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    capital = float(starting_capital)
    peak_capital = float(starting_capital)

    current_day: Any = None
    day_start_capital = float(starting_capital)
    halted_for_day = False

    signal_count = 0
    skipped_signal_count = 0
    rejected_for_risk_count = 0

    for row in work.itertuples(index=False):
        ts = pd.Timestamp(row.timestamp)
        symbol = str(row.symbol)
        close = float(row.close)
        high = float(row.high)
        low = float(row.low)
        row_day = row.date

        # Daily reset and daily loss kill-switch
        if current_day != row_day:
            current_day = row_day
            day_start_capital = capital
            halted_for_day = False

        if day_start_capital > 0:
            day_pnl_pct = (capital - day_start_capital) / day_start_capital
            if day_pnl_pct <= -float(daily_loss_limit_pct):
                halted_for_day = True

        # Exit management for existing position in this symbol.
        pos = open_positions.get(symbol)
        if pos is not None:
            pos.bars_held += 1
            exit_reason = None
            exit_price = None

            if pos.side == 1:
                hit_tp = high >= pos.target_price
                hit_sl = low <= pos.stop_price
                # Conservative tie-break: stop first when both touched.
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
                pnl = _compute_trade_pnl(pos.side, pos.entry_price, float(exit_price), pos.quantity)
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

        # Entry logic from 5m model signal.
        side = 1 if int(row.pred) == 1 else -1
        conf = float(row.confidence)
        if conf <= float(confidence_threshold):
            continue

        signal_count += 1

        if halted_for_day:
            skipped_signal_count += 1
            rejected_for_risk_count += 1
            continue

        if symbol in open_positions:
            skipped_signal_count += 1
            continue

        if len(open_positions) >= int(max_concurrent_trades):
            skipped_signal_count += 1
            rejected_for_risk_count += 1
            continue

        if close <= 0:
            skipped_signal_count += 1
            rejected_for_risk_count += 1
            continue

        stop_distance = close * float(stop_loss_pct)
        if stop_distance <= 0:
            skipped_signal_count += 1
            rejected_for_risk_count += 1
            continue

        size_factor = _size_reduction_factor(capital, peak_capital)
        risk_budget = capital * float(risk_per_trade_pct) * size_factor
        qty = int(risk_budget / stop_distance)

        # Hard notional cap to preserve capital realism (no leverage in simulation).
        max_affordable = int(capital / close)
        qty = min(qty, max_affordable)

        if qty <= 0:
            skipped_signal_count += 1
            rejected_for_risk_count += 1
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

        equity_rows.append(
            {
                "timestamp": str(ts),
                "capital": float(capital),
                "peak_capital": float(peak_capital),
                "drawdown_pct": float((peak_capital - capital) / max(peak_capital, 1e-12)),
                "open_positions": int(len(open_positions)),
            }
        )

    trades_df = pd.DataFrame(trade_rows)
    if trades_df.empty:
        summary = {
            "starting_capital": float(starting_capital),
            "ending_capital": float(capital),
            "total_profit": float(capital - starting_capital),
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "win_rate": 0.0,
            "max_drawdown": 0.0,
            "profit_factor": None,
            "signals_considered": int(signal_count),
            "signals_skipped": int(skipped_signal_count),
            "signals_rejected_by_risk": int(rejected_for_risk_count),
            "daily_loss_limit_pct": float(daily_loss_limit_pct),
            "max_concurrent_trades": int(max_concurrent_trades),
            "risk_per_trade_pct": float(risk_per_trade_pct),
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
    losses = int(len(trades_df) - wins)
    win_rate = float(wins / max(len(trades_df), 1))

    gross_profit = float(trades_df.loc[trades_df["pnl"] > 0, "pnl"].sum())
    gross_loss_abs = float(abs(trades_df.loc[trades_df["pnl"] < 0, "pnl"].sum()))
    profit_factor = float(gross_profit / gross_loss_abs) if gross_loss_abs > 0 else None

    equity_curve = starting_capital + trades_df["pnl"].cumsum()
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

    summary = {
        "starting_capital": float(starting_capital),
        "ending_capital": float(capital),
        "total_profit": float(capital - starting_capital),
        "total_trades": int(len(trades_df)),
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "max_drawdown": max_drawdown,
        "profit_factor": profit_factor,
        "signals_considered": int(signal_count),
        "signals_skipped": int(skipped_signal_count),
        "signals_rejected_by_risk": int(rejected_for_risk_count),
        "daily_loss_limit_pct": float(daily_loss_limit_pct),
        "max_concurrent_trades": int(max_concurrent_trades),
        "risk_per_trade_pct": float(risk_per_trade_pct),
    }
    return summary, trades_df, daily_df


def run_system(
    dataset_path: Path,
    model_path: Path,
    output_dir: Path,
    *,
    starting_capital: float,
    risk_per_trade_pct: float,
    max_concurrent_trades: int,
    confidence_threshold: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    daily_loss_limit_pct: float,
    max_holding_bars: int,
) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_path}")

    payload = _load_model_payload(model_path)
    model = payload["model"]
    feature_columns = list(payload["feature_columns"])

    df = pd.read_parquet(dataset_path)
    required_cols = {"timestamp", "symbol", "timeframe", "close", "high", "low"}
    missing = sorted(required_cols - set(df.columns))
    if missing:
        raise RuntimeError(f"Dataset missing required columns: {missing}")

    frame, X = _prepare_5m_data(df, feature_columns)

    # Production-like out-of-sample evaluation on the latest 20% timeline.
    split_idx = int(len(frame) * 0.8)
    split_idx = max(1, min(len(frame) - 1, split_idx))
    frame_test = frame.iloc[split_idx:].copy().reset_index(drop=True)
    X_test = X.iloc[split_idx:].copy().reset_index(drop=True)

    prob_buy = model.predict_proba(X_test)[:, 1].astype(np.float32)
    pred = (prob_buy >= 0.5).astype(np.int32)
    confidence = np.maximum(prob_buy, 1.0 - prob_buy).astype(np.float32)

    summary, trades_df, daily_df = _run_backtest(
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

    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "production_5m_system_report.json"
    trades_path = output_dir / "production_5m_system_trades.csv"
    daily_path = output_dir / "production_5m_system_daily_report.csv"

    trades_df.to_csv(trades_path, index=False)
    daily_df.to_csv(daily_path, index=False)

    report = {
        "dataset": str(dataset_path),
        "model": str(model_path),
        "timeframe": TIMEFRAME,
        "evaluation_window": {
            "train_rows": int(split_idx),
            "test_rows": int(len(frame_test)),
            "test_start": str(frame_test["timestamp"].min()) if not frame_test.empty else None,
            "test_end": str(frame_test["timestamp"].max()) if not frame_test.empty else None,
        },
        "system_config": {
            "risk_per_trade_pct": float(risk_per_trade_pct),
            "max_concurrent_trades": int(max_concurrent_trades),
            "drawdown_size_reduction": {
                "drawdown_gt_10pct": 0.50,
                "drawdown_gt_20pct": 0.25,
            },
            "confidence_threshold": float(confidence_threshold),
            "stop_loss_pct": float(stop_loss_pct),
            "take_profit_pct": float(take_profit_pct),
            "max_holding_bars": int(max_holding_bars),
            "daily_loss_limit_pct": float(daily_loss_limit_pct),
            "daily_halt_rule": "stop opening new trades once daily loss limit is hit",
        },
        "reporting": {
            "daily_metrics": ["daily_pnl", "win_rate", "drawdown"],
            "summary": summary,
        },
        "artifacts": {
            "report": str(report_path),
            "trades": str(trades_path),
            "daily_report": str(daily_path),
        },
    }

    report_path.write_text(json.dumps(_to_native(report), indent=2), encoding="utf-8")
    return _to_native(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Production-style 5m ML trading system with risk and capital management"
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
        help="Output directory for system report",
    )
    parser.add_argument("--starting-capital", type=float, default=100_000.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=0.01)
    parser.add_argument("--max-concurrent-trades", type=int, default=3)
    parser.add_argument("--confidence-threshold", type=float, default=0.60)
    parser.add_argument("--stop-loss-pct", type=float, default=0.005)
    parser.add_argument("--take-profit-pct", type=float, default=0.015)
    parser.add_argument("--daily-loss-limit-pct", type=float, default=0.03)
    parser.add_argument("--max-holding-bars", type=int, default=6)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = run_system(
        dataset_path=args.dataset,
        model_path=args.model,
        output_dir=args.output_dir,
        starting_capital=args.starting_capital,
        risk_per_trade_pct=args.risk_per_trade_pct,
        max_concurrent_trades=args.max_concurrent_trades,
        confidence_threshold=args.confidence_threshold,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        daily_loss_limit_pct=args.daily_loss_limit_pct,
        max_holding_bars=args.max_holding_bars,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
