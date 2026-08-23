#!/usr/bin/env python3
"""Run the isolated ETH BB/RSI mean-reversion bot. Does not start other strategies."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import load_settings
from src.errors import ConfigError
from src.logger import setup_logger
from src.runner import BBRSIRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="ETH 1m SMA Bollinger + RSI mean reversion")
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--dry-run", action="store_true", help="Scan signals without placing orders")
    args = parser.parse_args()

    logger = setup_logger()
    try:
        settings = load_settings(require_keys=not args.dry_run, dry_run=args.dry_run)
    except ConfigError as exc:
        logger.error("%s", exc)
        return 1

    runner = BBRSIRunner(settings, dry_run=args.dry_run)
    if args.once:
        result = runner.tick()
        if not result.success:
            logger.error("Tick failed: %s", result.error)
            return 1
        logger.info("Tick: %s | mark=%s", result.action, result.mark_price)
        return 0

    runner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
