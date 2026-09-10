#!/usr/bin/env python3
"""Compare live scanner entries against the backtest on the same candles."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.backtest import run_liquidity_backtest
from src.delta_data import closed_ohlcv, fetch_closed_ohlcv
from src.live import M15_DAYS, M1_DAYS, live_params, signal_on_last_bar
from src.swings import epoch_of


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
    print(f"Fetching ETHUSD {M15_DAYS}d 15m + {M1_DAYS}d 1m (India live, same as backtest)…")
    m15 = fetch_closed_ohlcv("ETHUSD", "15m", days=M15_DAYS)
    m1 = fetch_closed_ohlcv("ETHUSD", "1m", days=M1_DAYS)
    print(f"Closed bars: {len(m15)} 15m · {len(m1)} 1m")
    print(f"Window: {m1[0]['timestamp']} → {m1[-1]['timestamp']}")

    entries = []
    result = run_liquidity_backtest(m15, m1, params, entry_log=entries)
    print(
        f"\nBacktest on this window: {result.trade_count} fills · "
        f"net ${result.net_pnl:.2f} · wr {result.win_rate:.1%} · "
        f"{len(entries)} entries"
    )

    matched = 0
    failed = 0
    for expected in entries:
        cutoff = epoch_of(expected.entry_ts) + 60
        m15_cut = closed_ohlcv(m15, "15m", now=cutoff)
        m1_cut = [row for row in m1 if epoch_of(row["timestamp"]) <= epoch_of(expected.entry_ts)]
        found = signal_on_last_bar(m15_cut, m1_cut, params)
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

    now_signal = signal_on_last_bar(m15, m1, params)
    print(f"\nLive scan on latest closed 1m {m1[-1]['timestamp']}:")
    if now_signal is None:
        print("  No new entry this minute (same as backtest unless an entry sits on this bar).")
        last_is_entry = bool(entries) and entries[-1].entry_ts == m1[-1]["timestamp"]
        if last_is_entry:
            print("  FAIL: backtest entered on this bar but live scan did not.")
            failed += 1
        else:
            print("  OK: backtest also did not enter on this bar.")
    else:
        print(
            f"  Would {now_signal.side} {params.position_lots} lots @ {now_signal.entry_price:.2f} "
            f"SL {now_signal.stop_loss:.2f} TP {now_signal.target:.2f}"
        )

    print(f"\nReplay: {matched}/{len(entries)} entries match exactly, {failed} mismatches")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
