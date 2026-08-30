#!/usr/bin/env python3
"""Compare last-bar funding signals against a full backtest on the same candles."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.backtest import epoch_of, run_backtest
from src.config import STRATEGY_FUNDING
from src.delta_data import DeltaExchangeClient, closed_ohlcv
from src.funding_strategy import detect_funding_signal
from src.live import CANDLE_API_URL, LOOKBACK_DAYS, scan_closed_bars
from src.strategy import default_params


def replay() -> int:
    params = default_params(strategy=STRATEGY_FUNDING)
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    print(f"\n=== funding 1h {LOOKBACK_DAYS}d ===")
    rows = closed_ohlcv(client.fetch_historical_ohlcv("ETHUSD", "1h", days=LOOKBACK_DAYS), "1h")
    funding = client.fetch_funding_ohlcv("ETHUSD", days=LOOKBACK_DAYS, resolution="1h")
    print(f"Closed bars: {len(rows)}  {rows[0]['timestamp']} → {rows[-1]['timestamp']}")
    entries = []
    result = run_backtest(rows, params, funding_rows=funding, entry_log=entries)
    print(f"Backtest: {result.trade_count} fills · net ${result.net_pnl:.2f} · {len(entries)} entries")
    failed = 0
    matched = 0
    rate_by_ts = {row["timestamp"]: float(row["close"]) for row in funding}
    seen: list[dict] = []
    for expected in entries:
        seen = [row for row in funding if epoch_of(row["timestamp"]) <= epoch_of(expected.entry_ts)]
        price = [row for row in rows if row["timestamp"] == expected.entry_ts]
        found = detect_funding_signal(
            seen,
            price,
            params,
            current_rate=rate_by_ts.get(expected.entry_ts),
        )
        if found is None:
            failed += 1
            print(f"MISS  {expected.entry_ts} {expected.side}")
            continue
        if found.side != expected.side:
            failed += 1
            print(f"DIFF  {expected.entry_ts}: live={found.side} backtest={expected.side}")
            continue
        matched += 1
    now_signal, _, last_ts = scan_closed_bars(rows, params, funding_rows=funding)
    print(f"Latest bar {last_ts}: {'signal ' + now_signal.side if now_signal else 'flat'}")
    print(f"Replay: {matched}/{len(entries)} match, {failed} mismatches")
    return failed


def main() -> int:
    return 1 if replay() else 0


if __name__ == "__main__":
    raise SystemExit(main())
