from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

DEFAULT_RAW_FOLDER = ROOT / "experiments_v2" / "data" / "raw" / "1h"
DEFAULT_NIFTY_DAILY_PATH = ROOT / "data" / "nifty" / "daily" / "nifty_daily.csv"
DEFAULT_OUTPUT_DIR = ROOT / "backend" / "models" / "trend_1h"

from app.inference.train_pipeline import run_trend_1h_training


def main() -> None:
    parser = argparse.ArgumentParser(description="Run trend_1h training pipeline")
    parser.add_argument(
        "--raw-folder",
        default=str(DEFAULT_RAW_FOLDER),
        help=f"Folder containing 1h OHLCV CSV files (default: {DEFAULT_RAW_FOLDER})",
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
    args = parser.parse_args()

    run_trend_1h_training(
        raw_folder=Path(args.raw_folder),
        output_dir=Path(args.output_dir) if args.output_dir else None,
        nifty_daily_path=Path(args.nifty_daily_path) if args.nifty_daily_path else None,
        max_rows=args.max_rows,
        max_files=args.max_files,
    )


if __name__ == "__main__":
    main()
