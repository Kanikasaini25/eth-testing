#!/usr/bin/env python3
"""
Backtest the standalone "1H Liquidity Reversal" ETH strategy.

Fetches 1h + 1m ETHUSD candles from Delta Exchange and runs the strategy
without touching the existing LQDTY / YouTube pipeline strategies.

Examples:
  python scripts/run_1h_liquidity_reversal.py --days 7
  python scripts/run_1h_liquidity_reversal.py --days 3 --debug
  python scripts/run_1h_liquidity_reversal.py --days 14 --symbol ETHUSD
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest import result_to_dict
from src.config import OHLCV_DIR, REPORTS_DIR, ensure_data_dirs, get_env
from src.delta_data import DeltaExchangeClient, save_ohlcv, trim_ohlcv_to_days
from src.strategies.liquidity_reversal_1h import (
    STRATEGY_NAME,
    backtest_1h_liquidity_reversal,
    build_strategy_rule,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"Backtest {STRATEGY_NAME} on Delta Exchange ETH futures."
    )
    parser.add_argument(
        "--symbol",
        default=get_env("DELTA_SYMBOL", "ETHUSD"),
        help="Delta symbol (default: ETHUSD)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=min(30, int(get_env("BACKTEST_DAYS", "7"))),
        help="Number of 1m days to backtest (1h history fetched with extra buffer)",
    )
    parser.add_argument(
        "--starting-wallet",
        type=float,
        default=float(get_env("STARTING_WALLET_USD", "10000")),
        help="Starting wallet USD",
    )
    parser.add_argument(
        "--swing-strength",
        type=int,
        default=2,
        help="Fractal swing strength on 1H (bars left/right)",
    )
    parser.add_argument(
        "--confirmation-timeout",
        type=int,
        default=120,
        help="Max 1m bars after sweep to wait for confirmation (0 = no timeout)",
    )
    parser.add_argument(
        "--base-url",
        default=get_env("DELTA_BASE_URL", "https://api.india.delta.exchange"),
        help="Delta Exchange API base URL (use production for history if needed)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Print detailed setup / reject / entry logs",
    )
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Reuse existing data/ohlcv/{symbol}_1m.csv and {symbol}_1h.csv",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ensure_data_dirs()

    logging.basicConfig(
        level=logging.INFO if args.debug else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    days = max(1, min(args.days, 365))
    # Extra 1H history so swings can form before the 1m window starts.
    hour_days = days + 5

    minute_path = OHLCV_DIR / f"{args.symbol}_1m.csv"
    hour_path = OHLCV_DIR / f"{args.symbol}_1h.csv"

    if args.skip_fetch:
        from src.delta_data import load_ohlcv

        if not minute_path.exists() or not hour_path.exists():
            print(
                f"Missing cached OHLCV. Expected {minute_path} and {hour_path}",
                file=sys.stderr,
            )
            return 1
        minute_rows = load_ohlcv(str(minute_path))
        hour_rows = load_ohlcv(str(hour_path))
        print(f"Loaded cached 1m={len(minute_rows)} 1h={len(hour_rows)}")
    else:
        # Prefer India production history endpoint for public candles.
        history_url = args.base_url
        if "testnet" in history_url:
            history_url = "https://api.india.delta.exchange"
            print(f"Note: using {history_url} for historical candles (not testnet)")

        client = DeltaExchangeClient(base_url=history_url)
        print(f"Fetching {args.symbol} 1h ({hour_days}d) and 1m ({days}d)...")
        hour_rows = client.fetch_historical_ohlcv(
            symbol=args.symbol, resolution="1h", days=hour_days
        )
        minute_rows = client.fetch_historical_ohlcv(
            symbol=args.symbol, resolution="1m", days=days
        )
        minute_rows = trim_ohlcv_to_days(minute_rows, days, "1m")
        save_ohlcv(hour_rows, str(hour_path))
        save_ohlcv(minute_rows, str(minute_path))
        print(f"Saved {hour_path.name} ({len(hour_rows)}) and {minute_path.name} ({len(minute_rows)})")

    rule = build_strategy_rule(
        starting_wallet_usd=args.starting_wallet,
        swing_strength=args.swing_strength,
        confirmation_timeout_bars=args.confirmation_timeout,
        instrument=args.symbol,
    )

    events: list[dict] = []

    def on_event(name: str, payload: dict) -> None:
        if name in {
            "levels_locked",
            "liquidity_sweep",
            "first_confirmation_candle",
            "setup_rejected",
            "trade_entered",
            "trade_closed",
        }:
            events.append({"event": name, **({"payload": payload} if args.debug else {})})
            if args.debug:
                print(f"\n=== {name} ===")
                print(json.dumps(payload, indent=2, default=str))

    print(f"\nRunning {STRATEGY_NAME}...")
    result = backtest_1h_liquidity_reversal(
        minute_rows,
        hour_rows,
        rule,
        debug=args.debug,
        on_event=on_event,
    )

    out_json = REPORTS_DIR / "1h_liquidity_reversal_results.json"
    out_events = REPORTS_DIR / "1h_liquidity_reversal_events.json"
    payload = result_to_dict(result)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_events.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")

    print(f"\nStrategy : {result.rule_name}")
    print(f"Mode     : {result.backtest_mode}")
    print(f"Trades   : {result.total_trades}")
    print(f"Win rate : {result.win_rate}%")
    print(f"Return   : {result.total_return_pct}%")
    print(f"Buy&Hold : {result.buy_hold_return_pct}%")
    print(f"Max DD   : {result.max_drawdown_pct}%")
    print(f"Verdict  : {result.verdict}")
    print(f"Compliance: {json.dumps(result.rule_compliance, indent=2)}")
    print(f"\nResults  -> {out_json}")
    print(f"Events   -> {out_events}")

    if result.trades:
        print("\nTrades:")
        for trade in result.trades[:20]:
            print(
                f"  {trade.trade_type:4} {trade.entry_date} -> {trade.exit_date} "
                f"entry={trade.entry_price} exit={trade.exit_price} "
                f"pts={trade.points} pnl={trade.pnl_usd} ({trade.exit_reason})"
            )
        if len(result.trades) > 20:
            print(f"  ... {len(result.trades) - 20} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
