#!/usr/bin/env python3
"""Test Delta Exchange live API connection and optional test buy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.delta_trading import DeltaTradingClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Delta Exchange connection")
    parser.add_argument(
        "--buy",
        action="store_true",
        help="Place a test BUY order for 100 lots at current price",
    )
    parser.add_argument("--lots", type=int, default=100, help="Order size in lots")
    args = parser.parse_args()

    client = DeltaTradingClient()
    snapshot = client.test_connection()

    env_label = "PRODUCTION"
    print(f"Environment: {env_label}")
    print(f"Base URL: {snapshot.base_url}")
    print(f"Symbol: {snapshot.symbol}")

    if not snapshot.connected:
        print(f"Connection FAILED: {snapshot.error}")
        return 1

    print("Connection OK")
    print(f"Product ID: {snapshot.product_id}")
    if snapshot.ticker:
        print(f"Mark price: {snapshot.ticker.get('mark_price')}")

    print("\nWallet balances:")
    for wallet in snapshot.wallet_balances:
        asset = wallet.get("asset_symbol") or wallet.get("asset_id")
        balance = wallet.get("balance") or wallet.get("available_balance")
        print(f"  {asset}: {balance}")

    if snapshot.position:
        print("\nOpen position:")
        print(json.dumps(snapshot.position, indent=2))
    else:
        print("\nNo open position for this symbol.")

    if args.buy:
        print(f"\nPlacing test BUY order: {args.lots} lots...")
        result = client.place_buy_at_current_price(size=args.lots)
        if not result.success:
            print(f"Order FAILED: {result.error}")
            return 1
        print(
            f"Order OK ({result.order_type}) near ${result.price:,.2f} "
            f"for {result.size} lots"
        )
        if result.order:
            print(json.dumps(result.order, indent=2))
        if result.position:
            print("\nPosition after order:")
            print(json.dumps(result.position, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
