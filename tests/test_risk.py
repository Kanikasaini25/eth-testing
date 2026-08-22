from __future__ import annotations

import unittest

from src.risk import day_loss_reached, fill_risk_allowed, lots_for_risk, reached_one_r, target_from_fill


class RiskSizingTests(unittest.TestCase):
    def test_should_size_lots_to_one_percent_of_wallet(self) -> None:
        lots = lots_for_risk(
            10000,
            8.0,
            risk_pct=1.0,
            max_lots=20,
            use_risk_sizing=True,
        )
        self.assertEqual(lots, 12)

    def test_should_cap_lots_at_maximum(self) -> None:
        lots = lots_for_risk(
            10000,
            2.0,
            risk_pct=1.0,
            max_lots=20,
            use_risk_sizing=True,
        )
        self.assertEqual(lots, 20)

    def test_should_skip_when_risk_cannot_buy_one_lot(self) -> None:
        lots = lots_for_risk(
            50,
            10.0,
            risk_pct=1.0,
            min_lots=1,
            max_lots=20,
            use_risk_sizing=True,
        )
        self.assertEqual(lots, 0)


class FillPlanTests(unittest.TestCase):
    def test_should_set_target_from_fill_at_two_and_a_half_r(self) -> None:
        target = target_from_fill("long", 2400.0, 2392.0, min_target=15.0, reward_r=2.5)
        self.assertEqual(target, 2420.0)

    def test_should_reject_fill_that_cannot_make_two_r(self) -> None:
        allowed = fill_risk_allowed(
            2400.0,
            2392.0,
            max_sl_points=10.0,
            min_reward_to_risk=2.0,
            min_target=10.0,
            reward_r=1.5,
        )
        self.assertFalse(allowed)

    def test_should_stop_the_day_after_three_percent_loss(self) -> None:
        self.assertTrue(day_loss_reached(10000.0, 9690.0, 3.0))
        self.assertFalse(day_loss_reached(10000.0, 9800.0, 3.0))

    def test_should_detect_one_r_on_long(self) -> None:
        self.assertTrue(reached_one_r("long", 2400.0, 2392.0, 2409.0, 2399.0))
        self.assertFalse(reached_one_r("long", 2400.0, 2392.0, 2404.0, 2399.0))


if __name__ == "__main__":
    unittest.main()
