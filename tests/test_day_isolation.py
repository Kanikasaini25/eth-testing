from __future__ import annotations

import unittest

from src.backtest import (
    _impulse_opposite_candle,
    _liquidity_levels_from_intraday,
    reentry_after_profitable_close,
    same_day_reentry_allowed,
)


def _bar(ts: str, high: float, low: float, open_: float | None = None, close: float | None = None) -> dict:
    open_price = open_ if open_ is not None else (high + low) / 2
    close_price = close if close is not None else open_price
    return {
        "timestamp": ts,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
        "volume": 1,
    }


class DayIsolationTests(unittest.TestCase):
    def test_should_allow_reentry_when_close_is_same_utc_day(self) -> None:
        self.assertTrue(
            same_day_reentry_allowed(
                "2026-09-14T22:00:00+00:00",
                "2026-09-14T23:50:00+00:00",
            )
        )
        self.assertEqual(
            reentry_after_profitable_close(
                "2026-09-14T22:00:00+00:00",
                "2026-09-14T23:50:00+00:00",
                "short",
            ),
            "short",
        )

    def test_should_block_reentry_when_trade_spans_utc_midnight(self) -> None:
        self.assertFalse(
            same_day_reentry_allowed(
                "2026-09-14T22:00:00+00:00",
                "2026-09-15T01:10:00+00:00",
            )
        )
        self.assertEqual(
            reentry_after_profitable_close(
                "2026-09-14T22:00:00+00:00",
                "2026-09-15T01:10:00+00:00",
                "short",
            ),
            "",
        )

    def test_should_use_previous_utc_day_1m_high_low_for_levels(self) -> None:
        rows = [
            _bar("2026-09-10T00:00:00+00:00", 2502.0, 2410.0),
            _bar("2026-09-10T13:27:00+00:00", 2490.0, 2417.0),
            _bar("2026-09-11T13:08:00+00:00", 2510.0, 2495.0),
        ]
        daily = [
            {
                "timestamp": "2026-09-09T00:00:00+00:00",
                "open": 1,
                "high": 9999,
                "low": 1,
                "close": 1,
                "volume": 1,
            },
            {
                "timestamp": "2026-09-10T00:00:00+00:00",
                "open": 1,
                "high": 8888,
                "low": 2,
                "close": 1,
                "volume": 1,
            },
            {
                "timestamp": "2026-09-11T00:00:00+00:00",
                "open": 1,
                "high": 7777,
                "low": 3,
                "close": 1,
                "volume": 1,
            },
        ]
        levels = _liquidity_levels_from_intraday(rows, daily)
        self.assertEqual(levels["2026-09-11"]["upper"], 2502.0)
        self.assertEqual(levels["2026-09-11"]["lower"], 2410.0)

    def test_should_not_use_previous_day_impulse_candle(self) -> None:
        rows = [
            _bar("2026-09-10T23:59:00+00:00", 2600.0, 2400.0, 2410.0, 2405.0),
            _bar("2026-09-11T00:01:00+00:00", 2501.0, 2498.0, 2500.0, 2499.0),
            _bar("2026-09-11T00:02:00+00:00", 2504.0, 2499.0, 2499.0, 2503.0),
        ]
        opposite = _impulse_opposite_candle(rows, 2, "long", lookback=60)
        self.assertIsNotNone(opposite)
        assert opposite is not None
        self.assertEqual(opposite["low"], 2498.0)


if __name__ == "__main__":
    unittest.main()
