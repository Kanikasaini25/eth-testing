#!/usr/bin/env python3
"""
Full pipeline:
1. Fetch YouTube transcript
2. Extract trading techniques from transcript
3. Download Delta Exchange ETH futures 1d OHLCV
4. Backtest extracted rules on historical data
5. Save report
"""

from __future__ import annotations

import argparse
import json
import sys

from src.config import get_env
from src.pipeline import run_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest YouTube trading techniques on Delta Exchange ETH futures data."
    )
    parser.add_argument(
        "--url",
        default=get_env("YOUTUBE_URLS").split(",")[0] if get_env("YOUTUBE_URLS") else "",
        help="YouTube video URL",
    )
    parser.add_argument(
        "--symbol",
        default=get_env("DELTA_SYMBOL", "ETHUSD"),
        help="Delta Exchange symbol (default: ETHUSD)",
    )
    parser.add_argument(
        "--resolution",
        default=get_env("DELTA_RESOLUTION", "1d"),
        help="Candle resolution (default: 1d)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=min(365, int(get_env("BACKTEST_DAYS", "30"))),
        help="Backtest days: 1d liquidity lines + 1m entries (1 day = 1440 1m candles, max 365)",
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not args.url:
        print("Error: Provide --url or set YOUTUBE_URLS in .env", file=sys.stderr)
        return 1

    languages = [
        lang.strip() for lang in get_env("LANGUAGES", "en").split(",") if lang.strip()
    ]

    print("Step 1/5: Fetching YouTube transcript...")
    print("Step 2/5: Extracting trading rules from transcript...")
    print("Step 3/5: Downloading Delta Exchange OHLCV data...")
    print("Step 4/5: Running backtests...")
    print("Step 5/5: Generating report...")

    result = run_pipeline(
        video_url=args.url,
        symbol=args.symbol,
        resolution=args.resolution,
        days=args.days,
        starting_wallet_usd=args.starting_wallet,
        base_url=args.base_url,
        languages=languages,
    )

    print(f"  Transcript -> {result.transcript_path}")
    print(f"  Rules      -> {result.rules_path}")
    print(f"  OHLCV      -> {result.ohlcv_path}")
    print(f"  Report     -> {result.report_path}")
    print(f"  JSON       -> {result.results_path}")

    for backtest in result.results:
        print(
            f"    - {backtest.rule_name}: {backtest.verdict} | "
            f"trades={backtest.total_trades}, return={backtest.total_return_pct}%, "
            f"win_rate={backtest.win_rate}%"
        )

    print("\nPipeline complete.")
    print(json.dumps([item.verdict for item in result.results]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
