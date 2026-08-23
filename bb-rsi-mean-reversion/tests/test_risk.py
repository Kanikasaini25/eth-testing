import unittest

from src.risk import (
    build_trade_plan,
    estimated_round_trip_fee_usd,
    exact_stop_distance,
    price_pnl_usd,
    trade_risk_reward,
    trading_fee_usd,
)


class RiskTests(unittest.TestCase):
    def test_fixed_lots_are_always_100(self) -> None:
        plan = build_trade_plan(
            side="long",
            entry_price=3500.0,
            candle_low=3496.0,
            candle_high=3502.0,
            risk_usd=3.50,
            take_profit_usd=10.0,
            profit_lock_usd=5.0,
            max_profit_usd=20.0,
            contract_eth=0.01,
            tick_size=0.05,
        )
        self.assertEqual(plan.lots, 100)

    def test_100_lots_stop_equals_3_50(self) -> None:
        distance = exact_stop_distance(100, 3.50, 0.01)
        self.assertEqual(distance, 3.50)
        pnl = price_pnl_usd("long", 3500.0, 3496.50, 100, 0.01)
        self.assertEqual(round(abs(pnl), 2), 3.50)

    def test_delta_taker_fee_is_0_05_percent_per_side(self) -> None:
        entry_fee = trading_fee_usd(3500.0, 100, 0.01, 0.05)
        exit_fee = trading_fee_usd(3510.0, 100, 0.01, 0.05)
        self.assertAlmostEqual(entry_fee, 1.75, places=4)
        self.assertAlmostEqual(exit_fee, 1.755, places=4)
        gross = price_pnl_usd("long", 3500.0, 3510.0, 100, 0.01)
        self.assertEqual(gross, 10.0)
        self.assertAlmostEqual(gross - entry_fee - exit_fee, 10.0 - 1.75 - 1.755, places=4)

    def test_trade_plan_long_places_sl_below_and_tp_above(self) -> None:
        plan = build_trade_plan(
            side="long",
            entry_price=3500.0,
            candle_low=3496.0,
            candle_high=3502.0,
            risk_usd=3.50,
            take_profit_usd=10.0,
            profit_lock_usd=5.0,
            max_profit_usd=20.0,
            contract_eth=0.01,
            tick_size=0.05,
        )
        self.assertEqual(plan.lots, 100)
        self.assertLess(plan.stop_price, plan.entry_price)
        self.assertGreater(plan.take_profit_price, plan.entry_price)
        self.assertGreater(plan.profit_lock_price, plan.entry_price)
        self.assertLess(abs(plan.risk_usd - 3.50), 0.15)

    def test_trade_plan_short_is_mirrored(self) -> None:
        plan = build_trade_plan(
            side="short",
            entry_price=3500.0,
            candle_low=3496.0,
            candle_high=3504.0,
            risk_usd=3.50,
            take_profit_usd=10.0,
            profit_lock_usd=5.0,
            max_profit_usd=20.0,
            contract_eth=0.01,
            tick_size=0.05,
        )
        self.assertEqual(plan.lots, 100)
        self.assertGreater(plan.stop_price, plan.entry_price)
        self.assertLess(plan.take_profit_price, plan.entry_price)
        sl_pnl = price_pnl_usd("short", plan.entry_price, plan.stop_price, plan.lots, 0.01)
        self.assertLess(abs(sl_pnl + plan.risk_usd), 0.15)

    def test_net_of_fees_pushes_tp_beyond_gross_10(self) -> None:
        plan = build_trade_plan(
            side="long",
            entry_price=3500.0,
            candle_low=3496.0,
            candle_high=3502.0,
            risk_usd=3.50,
            take_profit_usd=10.0,
            profit_lock_usd=5.0,
            max_profit_usd=20.0,
            contract_eth=0.01,
            tick_size=0.05,
            fee_pct_per_side=0.05,
            net_of_fees=True,
        )
        fees = estimated_round_trip_fee_usd(3500.0, 100, 0.01, 0.05)
        gross = price_pnl_usd("long", plan.entry_price, plan.take_profit_price, 100, 0.01)
        self.assertGreater(gross, 10.0)
        self.assertAlmostEqual(gross, 10.0 + fees, delta=0.1)

    def test_gross_targets_stay_at_10_when_net_of_fees_off(self) -> None:
        plan = build_trade_plan(
            side="long",
            entry_price=3500.0,
            candle_low=3496.0,
            candle_high=3502.0,
            risk_usd=3.50,
            take_profit_usd=10.0,
            profit_lock_usd=5.0,
            max_profit_usd=20.0,
            contract_eth=0.01,
            tick_size=0.05,
            net_of_fees=False,
        )
        gross = price_pnl_usd("long", plan.entry_price, plan.take_profit_price, 100, 0.01)
        self.assertAlmostEqual(gross, 10.0, delta=0.1)

    def test_risk_reward_ratio_is_reward_over_risk(self) -> None:
        rr = trade_risk_reward(
            side="long",
            entry_price=3500.0,
            stop_price=3496.50,
            take_profit_price=3510.0,
            lots=100,
            contract_eth=0.01,
            realized_pnl=-3.50,
        )
        self.assertAlmostEqual(rr["risk_usd"], 3.50)
        self.assertAlmostEqual(rr["reward_usd"], 10.0)
        self.assertAlmostEqual(rr["ratio"], 10.0 / 3.50)
        self.assertAlmostEqual(rr["realized_r"], -1.0)


if __name__ == "__main__":
    unittest.main()
