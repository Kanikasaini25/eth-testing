#!/usr/bin/env python3
"""Run the live strategy on your Delta India account (ETH / tokenized gold)."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import get_env
from src.delta_trading import DeltaTradingClient, is_testnet_url
from src.email_notify import is_email_configured, send_test_email
from src.live import LiveGrabRunner, live_params
from src.product_specs import fetch_product_specs, lots_for_one_usd_per_point
from src.symbols import resolve_delta_symbol


def parse_args() -> argparse.Namespace:
    symbol_hint, _ = resolve_delta_symbol(get_env("DELTA_SYMBOL", "PAXGUSD"))
    default_lots = int(
        get_env("POSITION_LOTS")
        or str(lots_for_one_usd_per_point(fetch_product_specs(symbol_hint), usd_per_point=1.0))
    )
    parser = argparse.ArgumentParser(
        description=(
            "Live runner on Delta India. Gold = PAXGUSD/XAUTUSD "
            "(XAUUSD is not listed; alias maps to PAXGUSD)."
        )
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place real orders. Without this flag the script only prints signals.",
    )
    parser.add_argument("--loop", action="store_true", help="Keep scanning until Ctrl+C")
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Seconds between scans (default 10)",
    )
    parser.add_argument(
        "--symbol",
        default=get_env("DELTA_SYMBOL", "ETHUSD"),
        help="Futures symbol: ETHUSD, PAXGUSD, XAUTUSD (XAUUSD → PAXGUSD)",
    )
    parser.add_argument(
        "--lots",
        type=int,
        default=default_lots,
        help=f"Entry size in lots (default {default_lots} = ~$1 P&L per $1 move)",
    )
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send a test mail to NOTIFY_EMAIL and exit",
    )
    return parser.parse_args()


def print_account(symbol: str) -> None:
    broker = DeltaTradingClient(symbol=symbol)
    snap = broker.test_connection()
    net = "testnet" if is_testnet_url(snap.base_url) else "LIVE INDIA"
    if not snap.connected:
        print(f"Account: not connected ({snap.error})")
        return
    size = 0
    if snap.position:
        size = int(snap.position.get("size") or 0)
    print(f"Account: connected · {net} · {snap.symbol} · position {size} lots")


def main() -> int:
    args = parse_args()
    if args.test_email:
        result = send_test_email()
        print(result.message)
        return 0 if result.success else 1

    symbol, notice = resolve_delta_symbol(args.symbol)
    if notice:
        print(f"NOTE: {notice}")

    params = live_params(lots=int(args.lots))
    runner = LiveGrabRunner(params=params, symbol=symbol)
    dry_run = not args.live

    if args.live and not runner.broker.is_configured:
        print("Missing DELTA_API_KEY / DELTA_API_SECRET in .env")
        return 1

    if args.live and is_testnet_url(get_env("DELTA_BASE_URL", "")):
        print(
            "WARNING: DELTA_BASE_URL is testnet. Candles always use India LIVE; "
            "orders go to testnet. For real gold trading set "
            "DELTA_BASE_URL=https://api.india.delta.exchange"
        )

    print(
        "Hammer / Shooting Star live runner · "
        f"{'DRY-RUN (no orders)' if dry_run else 'LIVE ORDERS'} · {symbol}"
    )
    print(
        f"Rules: hammer/shooting star + 1m confirm only · {args.lots} lots · "
        f"T1 +{params.target_points:.0f}"
    )
    if is_email_configured():
        print("Email alerts: on (NOTIFY_EMAIL)")
    else:
        print("Email alerts: off (set SMTP_* and NOTIFY_EMAIL in .env)")
    if not dry_run:
        print_account(symbol)
        print("This places real futures orders. Ctrl+C to stop.")

    def run_tick() -> None:
        for line in runner.tick(dry_run=dry_run):
            print(f"  {line}")

    if args.loop:
        print(f"Loop every {args.interval}s (Ctrl+C to stop)")
        while True:
            try:
                run_tick()
            except Exception as exc:
                print(f"Tick failed: {exc}")
            time.sleep(max(args.interval, 5))
    run_tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
