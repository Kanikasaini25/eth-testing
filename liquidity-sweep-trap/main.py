#!/usr/bin/env python3
"""
Liquidity Sweep / Trap backtest runner.

Standalone project — no dependency on the parent youtube/ codebase.
"""

from __future__ import annotations

import argparse
import sys

from src.config import get_env
from src.pipeline import run_backtest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest Liquidity Sweep / Trap on Delta Exchange data."
    )
    parser.add_argument(
        "--symbol",
        default=get_env("DELTA_SYMBOL", "ETHUSD"),
        help="Delta Exchange symbol (default: ETHUSD)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=min(365, int(get_env("BACKTEST_DAYS", "30"))),
        help="Backtest period in days (default: 30, max: 365)",
    )
    parser.add_argument(
        "--starting-wallet",
        type=float,
        default=float(get_env("STARTING_WALLET_USD", "10000")),
        help="Starting wallet balance in USD (default: 10000)",
    )
    parser.add_argument(
        "--base-url",
        default=get_env("DELTA_BASE_URL", "https://api.india.delta.exchange"),
        help="Delta Exchange API base URL",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Use cached OHLCV CSV instead of downloading fresh data",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        pipeline = run_backtest(
            symbol=args.symbol.strip().upper(),
            days=args.days,
            starting_wallet_usd=args.starting_wallet,
            base_url=args.base_url,
            skip_download=args.skip_download,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result = pipeline.result
    print(f"  Report -> {pipeline.report_path}")
    print(f"  JSON   -> {pipeline.results_path}")
    print(
        f"  Result: {result.verdict} | sweeps={result.sweeps_detected}, "
        f"entries={result.confirmed_entries}, trades={result.total_trades}, "
        f"return={result.total_return_pct}%, win_rate={result.win_rate}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
