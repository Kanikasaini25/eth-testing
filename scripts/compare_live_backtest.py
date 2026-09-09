#!/usr/bin/env python3
"""Compare live scanner entries against the pattern backtest on the same candles."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.backtest import bar_seconds_for_resolution, run_pattern_backtest
from src.config import get_env
from src.delta_data import DeltaExchangeClient, closed_ohlcv
from src.live import CANDLE_API_URL, M1_DAYS, SIGNAL_DAYS, live_params, signal_on_last_bar
from src.swings import epoch_of
from src.symbols import resolve_delta_symbol


def _same(signal, expected) -> list[str]:
    misses = []
    for field in ("side", "entry_ts", "entry_price", "stop_loss", "target", "grab_ts", "swing_price"):
        left = getattr(signal, field)
        right = getattr(expected, field)
        if left != right:
            misses.append(f"{field}: live={left} backtest={right}")
    return misses


def main() -> int:
    params = live_params()
    symbol, _ = resolve_delta_symbol(get_env("DELTA_SYMBOL", "PAXGUSD"))
    resolution = get_env("DELTA_RESOLUTION", "15m") or "15m"
    if resolution in {"1d", "1w"}:
        resolution = "15m"
    bar_seconds = bar_seconds_for_resolution(resolution)
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    print(f"Fetching {symbol} {SIGNAL_DAYS}d {resolution} + {M1_DAYS}d 1m…")
    signal_rows = closed_ohlcv(
        client.fetch_historical_ohlcv(symbol, resolution, days=SIGNAL_DAYS), resolution
    )
    m1 = closed_ohlcv(client.fetch_historical_ohlcv(symbol, "1m", days=M1_DAYS), "1m")
    print(f"Closed bars: {len(signal_rows)} {resolution} · {len(m1)} 1m")
    print(f"Window: {m1[0]['timestamp']} → {m1[-1]['timestamp']}")

    entries = []
    result = run_pattern_backtest(
        signal_rows, m1, params, bar_seconds=bar_seconds, entry_log=entries
    )
    print(
        f"\nBacktest on this window: {result.trade_count} fills · "
        f"net ${result.net_pnl:.2f} · wr {result.win_rate:.1%} · "
        f"{len(entries)} entries"
    )

    matched = 0
    failed = 0
    for expected in entries:
        cutoff = epoch_of(expected.entry_ts) + 60
        sig_cut = closed_ohlcv(signal_rows, resolution, now=cutoff)
        m1_cut = [row for row in m1 if epoch_of(row["timestamp"]) <= epoch_of(expected.entry_ts)]
        found = signal_on_last_bar(sig_cut, m1_cut, params, bar_seconds=bar_seconds)
        if found is None:
            failed += 1
            print(f"MISS  {expected.entry_ts} {expected.side} @ {expected.entry_price:.2f} — live would not fire")
            continue
        diffs = _same(found, expected)
        if diffs:
            failed += 1
            print(f"DIFF  {expected.entry_ts} {expected.side}: {'; '.join(diffs)}")
            continue
        matched += 1
        print(
            f"OK    {expected.entry_ts} {expected.side:5} @ {expected.entry_price:.2f} "
            f"SL {expected.stop_loss:.2f} TP {expected.target:.2f}"
        )

    now_signal = signal_on_last_bar(signal_rows, m1, params, bar_seconds=bar_seconds)
    print(f"\nLive scan on latest closed 1m {m1[-1]['timestamp']}:")
    if now_signal is None:
        print("  No new entry this minute.")
    else:
        print(
            f"  Would {now_signal.side} {params.position_lots} lots @ {now_signal.entry_price:.2f} "
            f"SL {now_signal.stop_loss:.2f} TP {now_signal.target:.2f}"
        )

    print(f"\nReplay: {matched}/{len(entries)} entries match exactly, {failed} mismatches")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
