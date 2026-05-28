from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_RAW_FOLDER = ROOT / "experiments_v2" / "data" / "raw" / "5m"
DEFAULT_NIFTY_DAILY_PATH = ROOT / "data" / "nifty" / "daily" / "nifty_daily.csv"
DEFAULT_OUTPUT_DIR = ROOT / "backend" / "models" / "entry_5m"

from app.inference.train_pipeline import run_entry_5m_training


def main() -> None:
    parser = argparse.ArgumentParser(description="Run entry_5m training pipeline")
    parser.add_argument(
        "--raw-folder",
        default=str(DEFAULT_RAW_FOLDER),
        help=f"Folder containing 5m OHLCV CSV files (default: {DEFAULT_RAW_FOLDER})",
    )
    parser.add_argument(
        "--nifty-daily-path",
        default=str(DEFAULT_NIFTY_DAILY_PATH),
        help=f"NIFTY daily context CSV (default: {DEFAULT_NIFTY_DAILY_PATH})",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help=f"Model output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument("--max-rows", type=int, default=None)
    parser.add_argument("--max-files", type=int, default=None)
    parser.add_argument("--horizon", type=int, default=3, help="Lookahead horizon in candles (e.g. 3,6,9)")
    parser.add_argument("--label-mode", choices=["fixed", "atr"], default=None, help="Label mode: fixed or atr-adaptive (overrides env)")
    parser.add_argument("--future-return-threshold", type=float, default=None, help="Fixed future return threshold (e.g. 0.004 for 0.4%)")
    parser.add_argument("--atr-multiplier", type=float, default=None, help="ATR multiplier for ATR-adaptive mode (e.g. 0.6)")
    args = parser.parse_args()

    # Propagate optional label generation overrides via environment for compatibility
    if args.label_mode:
        os.environ["ENTRY_LABEL_MODE"] = str(args.label_mode)
    if args.future_return_threshold is not None:
        os.environ["ENTRY_FUTURE_RETURN_THRESHOLD"] = str(float(args.future_return_threshold))
    if args.atr_multiplier is not None:
        os.environ["ENTRY_ATR_MULTIPLIER"] = str(float(args.atr_multiplier))

    run_entry_5m_training(
        raw_folder=Path(args.raw_folder),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        nifty_daily_path=Path(args.nifty_daily_path) if args.nifty_daily_path else None,
        horizon=int(args.horizon),
        max_rows=args.max_rows,
        max_files=args.max_files,
    )


if __name__ == "__main__":
    main()
