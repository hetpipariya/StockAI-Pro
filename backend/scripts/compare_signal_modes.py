from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class CompareConfig:
    raw_dir: Path
    out_path: Path
    max_symbols: int = 25
    max_windows_per_symbol: int = 120
    window_size: int = 260
    min_window: int = 80
    step: int = 5


def _read_ohlcv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, low_memory=False)
    columns = {str(c).lower(): c for c in df.columns}

    required = ["open", "high", "low", "close", "volume"]
    missing = [name for name in required if name not in columns]
    if missing:
        raise ValueError(f"{path.name}: missing required columns {missing}")

    out = pd.DataFrame(
        {
            "open": pd.to_numeric(df[columns["open"]], errors="coerce"),
            "high": pd.to_numeric(df[columns["high"]], errors="coerce"),
            "low": pd.to_numeric(df[columns["low"]], errors="coerce"),
            "close": pd.to_numeric(df[columns["close"]], errors="coerce"),
            "volume": pd.to_numeric(df[columns["volume"]], errors="coerce"),
        }
    )
    out = out.replace([np.inf, -np.inf], np.nan).dropna()
    out = out[(out["close"] > 0) & (out["open"] > 0) & (out["high"] > 0) & (out["low"] > 0)]
    out = out.reset_index(drop=True)
    return out


def _empty_mode_stats() -> dict[str, Any]:
    return {
        "samples": 0,
        "hold_count": 0,
        "buy_count": 0,
        "sell_count": 0,
        "sum_confidence": 0.0,
        "trade_returns": [],
        "trade_correct": 0,
        "trade_eval_count": 0,
    }


def _update_mode_stats(stats: dict[str, Any], signal: str, confidence: float, next_return: float) -> None:
    side = str(signal or "HOLD").upper()
    conf = float(np.clip(float(confidence or 0.0), 0.0, 1.0))

    stats["samples"] += 1
    stats["sum_confidence"] += conf

    if side == "BUY":
        stats["buy_count"] += 1
    elif side == "SELL":
        stats["sell_count"] += 1
    else:
        stats["hold_count"] += 1

    if side not in {"BUY", "SELL"}:
        return

    if not np.isfinite(next_return):
        return

    side_sign = 1.0 if side == "BUY" else -1.0
    trade_ret = side_sign * float(next_return)
    stats["trade_returns"].append(trade_ret)
    stats["trade_eval_count"] += 1

    if trade_ret > 0:
        stats["trade_correct"] += 1


def _finalize_mode_stats(stats: dict[str, Any]) -> dict[str, Any]:
    samples = int(stats["samples"])
    buy_count = int(stats["buy_count"])
    sell_count = int(stats["sell_count"])
    hold_count = int(stats["hold_count"])
    actionable_count = buy_count + sell_count

    trade_returns = np.asarray(stats["trade_returns"], dtype=float)
    trade_eval_count = int(stats["trade_eval_count"])

    if trade_eval_count > 0:
        directional_precision = float(stats["trade_correct"] / trade_eval_count)
        false_trade_rate = float(1.0 - directional_precision)
        cumulative_return_proxy = float(np.sum(trade_returns))
        avg_return_per_trade_proxy = float(np.mean(trade_returns))
        win_rate_proxy = float(np.mean(trade_returns > 0))
    else:
        directional_precision = 0.0
        false_trade_rate = 0.0
        cumulative_return_proxy = 0.0
        avg_return_per_trade_proxy = 0.0
        win_rate_proxy = 0.0

    avg_confidence = float(stats["sum_confidence"] / max(samples, 1))

    return {
        "samples": samples,
        "hold_count": hold_count,
        "buy_count": buy_count,
        "sell_count": sell_count,
        "hold_rate": float(hold_count / max(samples, 1)),
        "actionable_count": actionable_count,
        "actionable_rate": float(actionable_count / max(samples, 1)),
        "avg_confidence": avg_confidence,
        "trade_eval_count": trade_eval_count,
        "directional_precision": directional_precision,
        "false_trade_rate": false_trade_rate,
        "cumulative_return_proxy": cumulative_return_proxy,
        "avg_return_per_trade_proxy": avg_return_per_trade_proxy,
        "win_rate_proxy": win_rate_proxy,
    }


def compare_modes(config: CompareConfig) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = Path(__file__).resolve().parents[1]

    import sys

    for candidate in [str(backend_root), str(repo_root)]:
        if candidate not in sys.path:
            sys.path.insert(0, candidate)

    from app.inference.models import ModelEnsemble, ensure_models_loaded  # pylint: disable=import-error

    ensure_models_loaded(max_retries=3)
    os.environ["SIGNAL_DECISION_MODE"] = "weighted"

    files = sorted(config.raw_dir.glob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No raw-data CSV files found in {config.raw_dir}")

    selected = files[: max(1, int(config.max_symbols))]

    legacy_stats = _empty_mode_stats()
    weighted_stats = _empty_mode_stats()

    per_symbol_rows: list[dict[str, Any]] = []

    for csv_path in selected:
        symbol = csv_path.stem.strip().upper()
        try:
            ohlcv = _read_ohlcv(csv_path)
        except Exception:
            continue

        if len(ohlcv) <= (config.min_window + 2):
            continue

        end_indices = list(range(config.min_window, len(ohlcv) - 1, max(1, config.step)))
        if config.max_windows_per_symbol > 0:
            end_indices = end_indices[-int(config.max_windows_per_symbol) :]

        symbol_legacy = _empty_mode_stats()
        symbol_weighted = _empty_mode_stats()

        for end_idx in end_indices:
            start_idx = max(0, end_idx - int(config.window_size) + 1)
            window = ohlcv.iloc[start_idx : end_idx + 1].copy()
            if len(window) < config.min_window:
                continue

            ltp = float(window["close"].iloc[-1])
            next_close = float(ohlcv["close"].iloc[end_idx + 1])
            if ltp <= 0:
                continue

            next_return = float((next_close - ltp) / ltp)

            result = ModelEnsemble.predict(
                symbol=symbol,
                ltp=ltp,
                features_seq=np.zeros((20, 10)),
                features_tab=np.zeros((1, 10)),
                ohlcv_df=window,
                debug=False,
            )

            models_meta = result.get("models", {}) if isinstance(result, dict) else {}
            legacy_meta = models_meta.get("legacy_decision", {}) if isinstance(models_meta, dict) else {}
            weighted_meta = models_meta.get("weighted_decision", {}) if isinstance(models_meta, dict) else {}

            legacy_signal = str(legacy_meta.get("signal", "HOLD"))
            legacy_conf = float(legacy_meta.get("confidence", 0.0) or 0.0)
            weighted_signal = str(weighted_meta.get("signal", result.get("signal", "HOLD")))
            weighted_conf = float(weighted_meta.get("confidence", result.get("confidence", 0.0)) or 0.0)

            _update_mode_stats(legacy_stats, legacy_signal, legacy_conf, next_return)
            _update_mode_stats(weighted_stats, weighted_signal, weighted_conf, next_return)
            _update_mode_stats(symbol_legacy, legacy_signal, legacy_conf, next_return)
            _update_mode_stats(symbol_weighted, weighted_signal, weighted_conf, next_return)

        sym_legacy_final = _finalize_mode_stats(symbol_legacy)
        sym_weighted_final = _finalize_mode_stats(symbol_weighted)

        if sym_legacy_final["samples"] > 0 and sym_weighted_final["samples"] > 0:
            per_symbol_rows.append(
                {
                    "symbol": symbol,
                    "legacy_hold_rate": sym_legacy_final["hold_rate"],
                    "weighted_hold_rate": sym_weighted_final["hold_rate"],
                    "legacy_actionable_rate": sym_legacy_final["actionable_rate"],
                    "weighted_actionable_rate": sym_weighted_final["actionable_rate"],
                    "legacy_precision": sym_legacy_final["directional_precision"],
                    "weighted_precision": sym_weighted_final["directional_precision"],
                    "legacy_return_proxy": sym_legacy_final["cumulative_return_proxy"],
                    "weighted_return_proxy": sym_weighted_final["cumulative_return_proxy"],
                }
            )

    legacy_final = _finalize_mode_stats(legacy_stats)
    weighted_final = _finalize_mode_stats(weighted_stats)

    delta = {
        "hold_rate_delta": float(weighted_final["hold_rate"] - legacy_final["hold_rate"]),
        "actionable_rate_delta": float(
            weighted_final["actionable_rate"] - legacy_final["actionable_rate"]
        ),
        "directional_precision_delta": float(
            weighted_final["directional_precision"] - legacy_final["directional_precision"]
        ),
        "false_trade_rate_delta": float(
            weighted_final["false_trade_rate"] - legacy_final["false_trade_rate"]
        ),
        "cumulative_return_proxy_delta": float(
            weighted_final["cumulative_return_proxy"] - legacy_final["cumulative_return_proxy"]
        ),
        "avg_return_per_trade_proxy_delta": float(
            weighted_final["avg_return_per_trade_proxy"]
            - legacy_final["avg_return_per_trade_proxy"]
        ),
    }

    payload = {
        "raw_dir": str(config.raw_dir),
        "selected_symbol_count": len(selected),
        "legacy": legacy_final,
        "weighted": weighted_final,
        "delta_weighted_minus_legacy": delta,
        "per_symbol": per_symbol_rows,
    }

    config.out_path.parent.mkdir(parents=True, exist_ok=True)
    with config.out_path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2)

    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare legacy hard-filter decision mode vs weighted-penalty mode."
    )
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("backend/app/cache/raw_data"),
        help="Directory containing raw OHLCV CSV files.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("experiments_v2/outputs/reports/signal_mode_comparison.json"),
        help="Output JSON report path.",
    )
    parser.add_argument("--max-symbols", type=int, default=25)
    parser.add_argument("--max-windows-per-symbol", type=int, default=120)
    parser.add_argument("--window-size", type=int, default=260)
    parser.add_argument("--min-window", type=int, default=80)
    parser.add_argument("--step", type=int, default=5)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    report = compare_modes(
        CompareConfig(
            raw_dir=args.raw_dir,
            out_path=args.out,
            max_symbols=args.max_symbols,
            max_windows_per_symbol=args.max_windows_per_symbol,
            window_size=args.window_size,
            min_window=args.min_window,
            step=args.step,
        )
    )

    print(json.dumps(report["legacy"], indent=2))
    print(json.dumps(report["weighted"], indent=2))
    print(json.dumps(report["delta_weighted_minus_legacy"], indent=2))
