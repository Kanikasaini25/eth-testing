#!/usr/bin/env python3
"""Synthetic checks for 1H Liquidity Reversal (no network)."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.strategies.liquidity_reversal_1h import (
    backtest_1h_liquidity_reversal,
    build_strategy_rule,
    find_confirmed_swings,
)


def _ts(base: datetime, hours: int = 0, minutes: int = 0) -> str:
    return (base + timedelta(hours=hours, minutes=minutes)).isoformat()


def _bar(ts: str, o: float, h: float, l: float, c: float) -> dict:
    return {
        "timestamp": ts,
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": 1.0,
    }


def test_swing_confirmation_no_lookahead() -> None:
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    # Build a clear swing high at hour 5 (index 5): high=120, neighbors lower.
    hours = []
    for i in range(12):
        high = 100.0
        low = 90.0
        if i == 5:
            high = 120.0
        if i in (3, 4, 6, 7):
            high = 110.0
        if i == 8:
            low = 70.0  # swing low
        if i in (6, 7, 9, 10):
            low = 80.0
        close = (high + low) / 2
        hours.append(_bar(_ts(base, hours=i), close - 1, high, low, close))

    highs, lows = find_confirmed_swings(hours, strength=2)
    assert any(abs(s.price - 120.0) < 1e-9 for s in highs), highs
    assert any(abs(s.price - 70.0) < 1e-9 for s in lows), lows
    # Swing high at index 5 confirmed at index 7 open time
    sh = next(s for s in highs if abs(s.price - 120.0) < 1e-9)
    assert sh.confirmed_at == _ts(base, hours=7)


def test_long_setup_enters_with_15pt_tp() -> None:
    """
    Construct locked swings, low sweep, then two green 1m candles with break.
    Expect: 80-lot partial at +15, then 20-lot runner on trailing stop.
    """
    base = datetime(2024, 6, 1, tzinfo=timezone.utc)

    # 1H: swing low at index 5 (price 100), swing high at index 10 (price 200)
    hours = []
    for i in range(20):
        high, low = 150.0, 120.0
        if i == 5:
            high, low = 130.0, 100.0
        if i in (3, 4, 6, 7):
            low = 110.0
        if i == 10:
            high, low = 200.0, 140.0
        if i in (8, 9, 11, 12):
            high = 180.0
        close = (high + low) / 2
        hours.append(_bar(_ts(base, hours=i), close, high, low, close))

    # 1m starts after swings are confirmed (need strength=2 after index 10 → confirmed hour 12)
    # Start 1m at hour 14 so both swings are known without look-ahead.
    m_start = base + timedelta(hours=14)
    minutes = []
    # Chop above swing low first
    for i in range(30):
        px = 130.0
        minutes.append(
            _bar(_ts(m_start, minutes=i), px, px + 1, px - 1, px)
        )
    # Sweep below 100
    minutes.append(_bar(_ts(m_start, minutes=30), 105, 106, 98, 99))
    # First green
    minutes.append(_bar(_ts(m_start, minutes=31), 100, 104, 99.5, 103))
    # Second green breaks first high 104
    minutes.append(_bar(_ts(m_start, minutes=32), 103, 106, 102.5, 105))
    # Reach partial TP = 104 + 15 = 119 without tagging trail yet
    minutes.append(_bar(_ts(m_start, minutes=33), 110, 119, 110, 118))
    # Continue higher, then pull back into 3pt trail (best=125 → trail=122)
    minutes.append(_bar(_ts(m_start, minutes=34), 118, 125, 118, 124))
    minutes.append(_bar(_ts(m_start, minutes=35), 124, 124.5, 121.5, 122))

    rule = build_strategy_rule(
        starting_wallet_usd=10_000,
        fee_pct_per_side=0.0,
        confirmation_timeout_bars=120,
        swing_strength=2,
    )
    result = backtest_1h_liquidity_reversal(minutes, hours, rule, debug=False)
    assert result.total_trades >= 1, result
    # Entry-based count: one entry may produce partial + runner legs
    legs = [t for t in result.trades if t.entry_price == 104.0]
    assert legs, result.trades
    assert legs[0].side == "long"
    partials = [t for t in legs if t.exit_reason.startswith("partial_target")]
    runners = [t for t in legs if t.exit_reason == "trailing_stop"]
    assert partials and partials[0].lots == 80 and abs(partials[0].points - 15.0) < 1e-6
    assert runners and runners[0].lots == 20
    print("LONG partial+trail OK:", legs)


def test_short_setup() -> None:
    base = datetime(2024, 7, 1, tzinfo=timezone.utc)
    hours = []
    for i in range(20):
        high, low = 150.0, 120.0
        if i == 5:
            high, low = 130.0, 100.0
        if i in (3, 4, 6, 7):
            low = 110.0
        if i == 10:
            high, low = 200.0, 140.0
        if i in (8, 9, 11, 12):
            high = 180.0
        close = (high + low) / 2
        hours.append(_bar(_ts(base, hours=i), close, high, low, close))

    m_start = base + timedelta(hours=14)
    minutes = []
    for i in range(30):
        px = 160.0
        minutes.append(_bar(_ts(m_start, minutes=i), px, px + 1, px - 1, px))
    # Sweep above 200
    minutes.append(_bar(_ts(m_start, minutes=30), 198, 202, 197, 201))
    # First red
    minutes.append(_bar(_ts(m_start, minutes=31), 200, 200.5, 196, 197))
    # Second red breaks first low 196
    minutes.append(_bar(_ts(m_start, minutes=32), 197, 197.5, 194, 195))
    # TP = 196 - 15 = 181
    minutes.append(_bar(_ts(m_start, minutes=33), 190, 190, 181, 182))
    minutes.append(_bar(_ts(m_start, minutes=34), 182, 182, 175, 176))
    minutes.append(_bar(_ts(m_start, minutes=35), 176, 179, 178, 178.5))

    rule = build_strategy_rule(fee_pct_per_side=0.0, swing_strength=2)
    result = backtest_1h_liquidity_reversal(minutes, hours, rule, debug=False)
    assert result.total_trades >= 1, result
    legs = [t for t in result.trades if t.entry_price == 196.0]
    assert legs and legs[0].side == "short"
    partials = [t for t in legs if t.exit_reason.startswith("partial_target")]
    assert partials and partials[0].lots == 80 and abs(partials[0].points - 15.0) < 1e-6
    print("SHORT partial OK:", legs)


def test_rejects_without_sweep() -> None:
    base = datetime(2024, 8, 1, tzinfo=timezone.utc)
    hours = []
    for i in range(20):
        high, low = 150.0, 120.0
        if i == 5:
            high, low = 130.0, 100.0
        if i in (3, 4, 6, 7):
            low = 110.0
        if i == 10:
            high, low = 200.0, 140.0
        if i in (8, 9, 11, 12):
            high = 180.0
        close = (high + low) / 2
        hours.append(_bar(_ts(base, hours=i), close, high, low, close))

    m_start = base + timedelta(hours=14)
    minutes = []
    for i in range(60):
        # Two greens with break but NEVER sweep
        if i == 40:
            minutes.append(_bar(_ts(m_start, minutes=i), 130, 134, 129.5, 133))
        elif i == 41:
            minutes.append(_bar(_ts(m_start, minutes=i), 133, 136, 132.5, 135))
        else:
            minutes.append(_bar(_ts(m_start, minutes=i), 130, 131, 129, 130))

    result = backtest_1h_liquidity_reversal(
        minutes, hours, build_strategy_rule(fee_pct_per_side=0.0), debug=False
    )
    assert result.total_trades == 0, result.trades
    print("No-sweep rejection OK")


if __name__ == "__main__":
    test_swing_confirmation_no_lookahead()
    test_long_setup_enters_with_15pt_tp()
    test_short_setup()
    test_rejects_without_sweep()
    print("\nAll synthetic checks passed.")
