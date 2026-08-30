#!/usr/bin/env python3
"""Rank funding books before trading them.

A carry only pays if funding stays on one side long enough to outrun the round
trip. This backtests each candidate at equal USD notional and reports whether
its funding was one-sided enough to be worth running.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.backtest import run_backtest
from src.config import (
    DEFAULT_NOTIONAL_USD,
    STRATEGY_FUNDING,
    lots_for_notional,
    parse_symbols,
    symbol_spec,
)
from src.delta_data import DeltaExchangeClient, closed_ohlcv
from src.funding_strategy import screen_funding_history
from src.live import CANDLE_API_URL
from src.strategy import default_params

CANDIDATES = "ETHUSD,BTCUSD,SOLUSD,XRPUSD"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen funding books")
    parser.add_argument("--symbols", default=CANDIDATES)
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--notional", type=float, default=DEFAULT_NOTIONAL_USD)
    parser.add_argument("--gst", type=float, default=18.0, help="GST percent on fees")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    rows: list[tuple[str, float, bool, int, float, float, str]] = []

    for symbol in parse_symbols(args.symbols):
        spec = symbol_spec(symbol)
        try:
            price = float(client.fetch_ticker(symbol).get("mark_price") or 0.0)
            candles = closed_ohlcv(
                client.fetch_historical_ohlcv(symbol, "1h", days=args.days), "1h"
            )
            funding = client.fetch_funding_ohlcv(symbol, days=args.days, resolution="1h")
        except Exception as exc:
            print(f"{symbol}: fetch failed ({exc})")
            continue

        report = screen_funding_history(funding, symbol=symbol)
        lots = lots_for_notional(symbol, price, args.notional)
        params = default_params(
            strategy=STRATEGY_FUNDING, lots=lots, symbol=symbol, notional_usd=args.notional
        )
        params.gst_pct = args.gst
        result = run_backtest(candles, params, funding_rows=funding)
        fees_ex = result.total_fees / (1.0 + args.gst / 100.0)
        rows.append(
            (
                symbol,
                report.one_sided_share,
                report.tradable,
                result.trade_count,
                result.net_pnl,
                result.total_fees,
                f"{lots} lots = {params.hedge_qty():g} vs {spec.spot}",
            )
        )
        print(
            f"{symbol:8} {report.one_sided_share:5.0%} {report.dominant:8} "
            f"fills={result.trade_count:>3}  net=${result.net_pnl:+9,.2f}  "
            f"fees=${fees_ex:,.2f}+gst  {'TRADE' if report.tradable else 'SKIP'}"
        )

    if not rows:
        return 1
    print(f"\nRanked by net over {args.days}d at ~${args.notional:,.0f} notional each:")
    for symbol, share, tradable, fills, net, fees, sizing in sorted(
        rows, key=lambda item: item[4], reverse=True
    ):
        flag = "trade" if tradable else "skip (funding flips too often)"
        print(f"  {symbol:8} ${net:+9,.2f}  {share:.0%} one-sided  {fills:>3} fills  {flag}")
        print(f"           {sizing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
