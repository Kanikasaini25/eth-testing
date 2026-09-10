#!/usr/bin/env python3
"""Run the 15m liquidity-grab strategy on your Delta India account."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import get_env, get_market_data_base_url, get_trade_base_url
from src.delta_trading import DeltaTradingClient, trade_network_label
from src.email_notify import is_email_configured, send_test_email
from src.live import LiveGrabRunner, live_params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="15m liquidity grab + 1m confirmation on Delta ETHUSD"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place orders on the demo/testnet account. Without this flag the script only prints signals.",
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
        help="Futures symbol (default ETHUSD)",
    )
    parser.add_argument("--lots", type=int, default=100, help="Entry size in lots")
    parser.add_argument(
        "--test-email",
        action="store_true",
        help="Send a test mail to NOTIFY_EMAIL and exit",
    )
    return parser.parse_args()


def print_endpoints() -> None:
    data_url = get_market_data_base_url()
    trade_url = get_trade_base_url()
    print(f"Market data: India live · {data_url}")
    print(f"Orders: {trade_network_label(trade_url)} · {trade_url}")


def print_account(symbol: str) -> bool:
    broker = DeltaTradingClient(symbol=symbol)
    snap = broker.test_connection()
    net = trade_network_label(snap.base_url)
    if not snap.connected:
        print(f"Account: not connected ({snap.error})")
        if "ip_not_whitelisted" in (snap.error or ""):
            print(
                "Whitelist this machine's IP on the demo API key at "
                "https://demo.delta.exchange/app/account/manageapikeys"
            )
        return False
    size = 0
    if snap.position:
        size = int(snap.position.get("size") or 0)
    print(f"Account: connected · {net} · {snap.symbol} · position {size} lots")
    return True


def main() -> int:
    args = parse_args()
    if args.test_email:
        result = send_test_email()
        print(result.message)
        return 0 if result.success else 1

    params = live_params(lots=int(args.lots))
    runner = LiveGrabRunner(params=params, symbol=args.symbol.upper())
    dry_run = not args.live

    if args.live and not runner.broker.is_configured:
        print("Missing DELTA_API_KEY / DELTA_API_SECRET in .env")
        return 1

    print(
        "15m liquidity grab live runner · "
        f"{'DRY-RUN (no orders)' if dry_run else 'DEMO ORDERS'} · {args.symbol}"
    )
    print_endpoints()
    print(
        f"Rules: 100 lots default, 80% off at +{params.target_points:.0f}, "
        f"20% runner +{params.runner_target_points:.0f}, stop at grab extreme"
    )
    if is_email_configured():
        print("Email alerts: on (NOTIFY_EMAIL)")
    else:
        print("Email alerts: off (set SMTP_* and NOTIFY_EMAIL in .env)")
    if not dry_run:
        if not print_account(args.symbol.upper()):
            return 1
        print("This places futures orders on the demo/testnet account. Ctrl+C to stop.")

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
