#!/usr/bin/env python3
"""Run the funding cash-and-carry hedge on Delta India across one or more books."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import (
    DEFAULT_NOTIONAL_USD,
    DEFAULT_SYMBOLS,
    get_env,
    parse_symbols,
)
from src.delta_trading import DeltaTradingClient, is_testnet_url
from src.email_notify import is_email_configured, send_test_email
from src.live import build_runners, describe_book, screen_symbol


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Funding cash-and-carry live runner")
    parser.add_argument("--live", action="store_true", help="Place real orders")
    parser.add_argument("--loop", action="store_true", help="Keep scanning until Ctrl+C")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between scans")
    parser.add_argument(
        "--symbols",
        default=get_env("SYMBOLS", ",".join(DEFAULT_SYMBOLS)),
        help="Comma-separated perps, e.g. ETHUSD,BTCUSD",
    )
    parser.add_argument(
        "--notional",
        type=float,
        default=DEFAULT_NOTIONAL_USD,
        help="USD exposure per book; lots are derived from it",
    )
    parser.add_argument("--lots", type=int, help="Fixed lots per book instead of notional sizing")
    parser.add_argument(
        "--skip-screen",
        action="store_true",
        help="Trade a book even if its funding is not one-sided enough",
    )
    parser.add_argument("--test-email", action="store_true")
    return parser.parse_args()


def print_account(symbol: str) -> None:
    broker = DeltaTradingClient(symbol=symbol)
    snap = broker.test_connection()
    net = "testnet" if is_testnet_url(snap.base_url) else "LIVE INDIA"
    if not snap.connected:
        print(f"  {symbol}: not connected ({snap.error})")
        return
    size = int(snap.position.get("size") or 0) if snap.position else 0
    print(f"  {symbol}: connected · {net} · position {size} lots")


def screen_books(symbols: tuple[str, ...], skip_screen: bool) -> list[str]:
    """Drop books whose funding flips too often to outrun the round trip."""
    keep: list[str] = []
    for symbol in symbols:
        try:
            report = screen_symbol(symbol)
        except Exception as exc:
            print(f"  {symbol}: screen failed ({exc}); trading anyway")
            keep.append(symbol)
            continue
        verdict = "OK" if report.tradable else "SKIP"
        print(f"  {symbol}: {verdict} · {report.note} · {report.readings} readings")
        if report.tradable or skip_screen:
            keep.append(symbol)
    return keep


def main() -> int:
    args = parse_args()
    if args.test_email:
        result = send_test_email()
        print(result.message)
        return 0 if result.success else 1

    symbols = parse_symbols(args.symbols)
    dry_run = not args.live

    print(f"funding runner · {'DRY-RUN (no orders)' if dry_run else 'LIVE ORDERS'}")
    print("Screening funding history (365d):")
    symbols = tuple(screen_books(symbols, args.skip_screen))
    if not symbols:
        print("No book passed the funding screen. Use --skip-screen to override.")
        return 1

    runners = build_runners(symbols, lots=args.lots, notional_usd=args.notional)
    if args.live and not all(runner.broker.is_configured for runner in runners):
        print("Missing DELTA_API_KEY / DELTA_API_SECRET in .env")
        return 1

    first = runners[0].params
    print("Books:")
    for runner in runners:
        print(f"  {describe_book(runner.params, runner.state.entry_price)}")
    print(
        f"|rate| >= {first.funding_threshold_pct}% x {first.funding_confirm_periods} periods; "
        f"futures maker={first.funding_futures_maker}; "
        f"exit confirm={first.funding_exit_confirm}; "
        f"momentum={first.funding_require_momentum}; "
        f"skip {first.funding_skip_minutes_before_settle}m before settlement"
    )
    print("Email alerts: on" if is_email_configured() else "Email alerts: off")
    if not dry_run:
        print("Accounts:")
        for runner in runners:
            print_account(runner.symbol)
        print("This places real orders. Ctrl+C to stop.")

    def run_tick() -> None:
        for runner in runners:
            try:
                for line in runner.tick(dry_run=dry_run):
                    print(f"  {line}")
            except Exception as exc:
                print(f"  {runner.symbol} tick failed: {exc}")

    if args.loop:
        print(f"Loop every {args.interval}s (Ctrl+C to stop)")
        while True:
            run_tick()
            time.sleep(max(args.interval, 5))
    run_tick()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
