#!/usr/bin/env python3
"""Run 15m previous-day POC live strategy on Delta demo/live account."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.live_strategy import LivePocRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 15m previous-day POC live strategy")
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--loop", action="store_true", help="Run continuously every N seconds")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between ticks")
    parser.add_argument("--dry-run", action="store_true", help="Scan signals without placing orders")
    parser.add_argument("--enable", action="store_true", help="Mark strategy as enabled in state")
    args = parser.parse_args()

    runner = LivePocRunner()
    if args.enable:
        runner.set_enabled(True)

    def run_tick() -> int:
        result = runner.tick(dry_run=args.dry_run)
        if not result.success:
            print(f"Tick FAILED: {result.error}")
            return 1
        print(
            f"Mark: {result.mark_price} | POC: {result.poc} | VAL: {result.val} | "
            f"VAH: {result.vah} | Bias: {result.bias or '—'}"
        )
        print(f"Position: {result.exchange_position} lots | Tracked: {result.in_position}")
        for action in result.actions:
            print(f"  - {action}")
        return 0

    if args.loop:
        print(f"Live strategy loop every {args.interval}s (Ctrl+C to stop)")
        while True:
            code = run_tick()
            if code != 0:
                print(f"Retrying in {args.interval}s...")
            time.sleep(args.interval)

    return run_tick()


if __name__ == "__main__":
    raise SystemExit(main())
