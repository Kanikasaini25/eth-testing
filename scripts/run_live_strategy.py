#!/usr/bin/env python3
"""Run LQDTY 1d/1m or 15m POC live strategy on the same Delta demo/live account."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.live_poc_strategy import LivePocRunner
from src.live_strategy import LiveLiquidityRunner


def _print_lqdty(result) -> None:
    print(f"Mark: {result.mark_price} | Upper: {result.upper_level} | Lower: {result.lower_level}")
    print(f"Position: {result.exchange_position} lots | Tracked: {result.in_position}")


def _print_poc(result) -> None:
    print(
        f"Mark: {result.mark_price} | POC: {result.poc} | VAL: {result.val} | "
        f"VAH: {result.vah} | Bias: {result.bias or '—'}"
    )
    print(f"Position: {result.exchange_position} lots | Tracked: {result.in_position}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run live strategy on Delta demo/live")
    parser.add_argument(
        "--strategy",
        choices=["lqdty", "m15"],
        default="lqdty",
        help="lqdty = 1d lines + 1m entries; m15 = previous-day POC on 15m",
    )
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--loop", action="store_true", help="Run continuously every N seconds")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between ticks")
    parser.add_argument("--dry-run", action="store_true", help="Scan signals without placing orders")
    parser.add_argument("--enable", action="store_true", help="Mark strategy as enabled in state")
    args = parser.parse_args()

    if args.strategy == "m15":
        runner = LivePocRunner()
        print_result = _print_poc
        label = "15m POC"
    else:
        runner = LiveLiquidityRunner()
        print_result = _print_lqdty
        label = "LQDTY 1d/1m"

    if args.enable:
        runner.set_enabled(True)

    def run_tick() -> int:
        result = runner.tick(dry_run=args.dry_run)
        if not result.success:
            print(f"Tick FAILED: {result.error}")
            return 1
        print_result(result)
        for action in result.actions:
            print(f"  - {action}")
        return 0

    if args.loop:
        print(f"{label} loop every {args.interval}s (Ctrl+C to stop)")
        while True:
            code = run_tick()
            if code != 0:
                print(f"Retrying in {args.interval}s...")
            time.sleep(args.interval)

    return run_tick()


if __name__ == "__main__":
    raise SystemExit(main())
