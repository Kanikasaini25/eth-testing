from __future__ import annotations

import unittest

from src.trade_filters import (
    entry_reward_points,
    fill_stop_allowed,
    in_utc_session,
    m15_trend,
    passes_stop_filters,
    resolve_stop,
    trend_allows,
)


class StopFilterTests(unittest.TestCase):
    def test_should_reject_stop_that_is_tighter_than_minimum(self) -> None:
        allowed = passes_stop_filters(
            "long",
            2400,
            2398,
            target_points=15,
            min_sl_points=5,
            max_sl_points=10,
            min_reward_to_risk=1.5,
        )
        self.assertFalse(allowed)

    def test_should_reject_stop_that_cannot_make_15_point_target(self) -> None:
        allowed = passes_stop_filters(
            "long",
            2400,
            2385,
            target_points=15,
            min_sl_points=5,
            max_sl_points=10,
            min_reward_to_risk=1.5,
        )
        self.assertFalse(allowed)

    def test_should_allow_stop_inside_quality_band(self) -> None:
        allowed = passes_stop_filters(
            "long",
            2400,
            2392,
            target_points=15,
            min_sl_points=5,
            max_sl_points=10,
            min_reward_to_risk=1.5,
        )
        self.assertTrue(allowed)

    def test_should_use_two_r_when_larger_than_min_target(self) -> None:
        self.assertEqual(entry_reward_points(8.0, 15.0, 2.0), 16.0)

    def test_should_keep_min_target_when_two_r_is_smaller(self) -> None:
        self.assertEqual(entry_reward_points(5.0, 15.0, 2.0), 15.0)

    def test_should_allow_london_new_york_hours(self) -> None:
        self.assertTrue(in_utc_session("2026-08-21T10:00:00+00:00", 8, 20))
        self.assertFalse(in_utc_session("2026-08-21T03:00:00+00:00", 8, 20))


class TrendFilterTests(unittest.TestCase):
    def test_should_read_uptrend_from_rising_15m_closes(self) -> None:
        bars = [{"close": 2000 + index} for index in range(10)]
        self.assertEqual(m15_trend(bars, lookback=8), "up")
        self.assertTrue(trend_allows("long", "up"))
        self.assertFalse(trend_allows("short", "up"))

    def test_should_allow_both_sides_when_trend_is_flat(self) -> None:
        self.assertTrue(trend_allows("long", "flat"))
        self.assertTrue(trend_allows("short", "flat"))

    def test_should_reject_fill_when_stop_is_wider_than_max(self) -> None:
        self.assertFalse(fill_stop_allowed(2400.0, 2388.0, 10.0))
        self.assertTrue(fill_stop_allowed(2400.0, 2392.0, 10.0))


if __name__ == "__main__":
    unittest.main()
