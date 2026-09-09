#!/usr/bin/env python3
"""Run Hammer / Shooting Star locally on your laptop via MT5 (PDMBulls demo/live).

No cloud server needed. Requirements:
  1. MetaTrader 5 installed on this machine (Windows recommended)
  2. Logged into PDMBulls demo or live in the MT5 terminal
  3. pip install MetaTrader5
  4. Fill MT5_* values in .env
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.config import get_env
from src.mt5_broker import Mt5Broker, mt5_available
from src.mt5_live import Mt5PatternRunner, mt5_live_params


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local MT5 Hammer/Shooting Star runner (PDMBulls demo/live on this laptop)"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Place real orders on the connected MT5 account (demo or live). Default is dry-run.",
    )
    parser.add_argument("--loop", action="store_true", help="Keep scanning until Ctrl+C")
    parser.add_argument("--interval", type=int, default=10, help="Seconds between scans")
    parser.add_argument(
        "--symbol",
        default=get_env("MT5_SYMBOL", "XAUUSD"),
        help="MT5 symbol (default XAUUSD)",
    )
    parser.add_argument(
        "--volume",
        type=float,
        default=float(get_env("MT5_VOLUME", "0.10") or "0.10"),
        help="Order volume in MT5 lots (e.g. 0.10)",
    )
    parser.add_argument(
        "--candle",
        default=get_env("MT5_CANDLE", "15m"),
        help="Pattern candle timeframe (5m/15m/30m/1h)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only test MT5 login to PDMBulls and print account balance",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not mt5_available():
        print(
            "MetaTrader5 package missing or unsupported on this OS.\n"
            "On your Windows laptop:\n"
            "  1. Install MT5 from PDMBulls and log into your DEMO account\n"
            "  2. pip install MetaTrader5\n"
            "  3. python scripts/run_mt5_local.py --check\n"
            "  4. python scripts/run_mt5_local.py --loop          # dry-run\n"
            "  5. python scripts/run_mt5_local.py --live --loop   # place demo orders"
        )
        return 1

    broker = Mt5Broker(symbol=args.symbol.upper())
    if not broker.is_configured:
        print("Set MT5_LOGIN, MT5_PASSWORD, MT5_SERVER in .env (PDMBulls demo credentials)")
        return 1

    snap = broker.snapshot()
    if not snap.connected:
        print(f"MT5 not connected: {snap.error}")
        print("Open MetaTrader 5 on this laptop, login to PDMBulls, then retry.")
        return 1

    print(
        f"Connected · {snap.server} · login {snap.login} · "
        f"{snap.currency} balance {snap.balance:.2f} · equity {snap.equity:.2f} · "
        f"{snap.symbol} bid {snap.bid:.2f} ask {snap.ask:.2f}"
    )
    if args.check:
        broker.shutdown()
        return 0

    params = mt5_live_params(volume=args.volume)
    runner = Mt5PatternRunner(
        broker=broker,
        params=params,
        candle_resolution=args.candle,
        volume=args.volume,
    )
    dry_run = not args.live
    mode = "DRY-RUN (signals only)" if dry_run else "LIVE ORDERS on MT5"
    print(f"Hammer/Shooting Star · local laptop · {mode} · {args.symbol} · vol {args.volume}")
    print(
        f"Candle {args.candle} · T1 max({params.target_points:.0f}, "
        f"{params.target_risk_multiple:.1f}x risk) · scale {params.partial_exit_pct:.0f}% / T3 close all"
    )
    print("No cloud server — this process must keep running on your laptop.")
    if not dry_run:
        print("WARNING: --live will place orders on the logged-in MT5 account (demo or real).")

    def run_tick() -> None:
        for line in runner.tick(dry_run=dry_run):
            print(f"  {line}")

    try:
        if args.loop:
            print(f"Loop every {args.interval}s (Ctrl+C to stop)")
            while True:
                try:
                    run_tick()
                except Exception as exc:
                    print(f"Tick failed: {exc}")
                time.sleep(max(args.interval, 5))
        else:
            run_tick()
    finally:
        broker.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
