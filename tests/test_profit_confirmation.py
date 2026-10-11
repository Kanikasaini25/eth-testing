from __future__ import annotations

import unittest

from src.profit_confirmation import (
    CONFIRMED,
    FAILED,
    PENDING,
    confirm_profit_points,
    confirmation_status,
    confirmation_trigger,
)


class ConfirmProfitPointsTest(unittest.TestCase):
    def test_should_read_points_when_configured(self) -> None:
        self.assertEqual(confirm_profit_points({"confirm_profit_points": 8}), 8.0)

    def test_should_disable_when_missing_or_negative(self) -> None:
        self.assertEqual(confirm_profit_points({}), 0.0)
        self.assertEqual(confirm_profit_points({"confirm_profit_points": None}), 0.0)
        self.assertEqual(confirm_profit_points({"confirm_profit_points": -3}), 0.0)


class ConfirmationTriggerTest(unittest.TestCase):
    def test_should_offset_in_trade_direction(self) -> None:
        self.assertEqual(confirmation_trigger("long", 2000.0, 8), 2008.0)
        self.assertEqual(confirmation_trigger("short", 2000.0, 8), 1992.0)

    def test_should_reject_unknown_side(self) -> None:
        with self.assertRaises(ValueError):
            confirmation_trigger("flat", 2000.0, 8)


class ConfirmationStatusTest(unittest.TestCase):
    def test_should_confirm_long_when_trigger_reached(self) -> None:
        status = confirmation_status("long", trigger=2008, stop_loss=1990, high=2009, low=1995)
        self.assertEqual(status, CONFIRMED)

    def test_should_fail_short_when_stop_hit(self) -> None:
        status = confirmation_status("short", trigger=1992, stop_loss=2010, high=2011, low=1995)
        self.assertEqual(status, FAILED)

    def test_should_stay_pending_when_neither_level_touched(self) -> None:
        status = confirmation_status("long", trigger=2008, stop_loss=1990, high=2005, low=1995)
        self.assertEqual(status, PENDING)

    def test_should_fail_when_bar_touches_both_levels(self) -> None:
        status = confirmation_status("short", trigger=1992, stop_loss=2010, high=2010, low=1990)
        self.assertEqual(status, FAILED)


if __name__ == "__main__":
    unittest.main()
