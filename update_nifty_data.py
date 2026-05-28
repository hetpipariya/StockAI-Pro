from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv

for _env_path in (ROOT / ".env", ROOT / "backend" / ".env"):
    if _env_path.is_file():
        load_dotenv(dotenv_path=_env_path, override=True)

logger = logging.getLogger(__name__)

from app.data.nifty_updater import NiftyUpdater
from app.connectors import get_market_data_connector


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    logger.info(
        "[BOOT] runtime env reloaded; UPSTOX_ACCESS_TOKEN loaded=%s length=%d source=runtime_env",
        bool(os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()),
        len(os.getenv("UPSTOX_ACCESS_TOKEN", "").strip()),
    )

    parser = argparse.ArgumentParser(description="Update canonical NIFTY datasets")
    parser.add_argument("--granularity", choices=["daily", "1h", "5m", "all"], default="all")
    parser.add_argument("--backfill-days", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--symbol-token", type=str, default=None)
    args = parser.parse_args()

    connector = get_market_data_connector()
    try:
        connector.ensure_login()
        snapshot = connector.active_snapshot()
        logger.info(
            "[BOOT] broker validation OK active=%s primary=%s fallback=%s",
            snapshot.get("active_broker"),
            snapshot.get("primary"),
            snapshot.get("fallback"),
        )
    except Exception as exc:
        logger.error("[BOOT] broker validation failed: %s", exc)
        raise

    updater = NiftyUpdater(symbol_token=args.symbol_token)
    targets = [args.granularity] if args.granularity != "all" else ["daily", "1h", "5m"]
    for target in targets:
        updater.update(
            granularity=target,
            backfill_days=args.backfill_days,
            force=args.force,
            strict=args.strict,
        )


if __name__ == "__main__":
    main()
