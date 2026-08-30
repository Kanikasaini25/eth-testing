from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.funding_strategy import detect_funding_signal, should_enter_carry, should_exit_carry
from src.strategy import StrategyParams


def bar(index: int | str, open_: float, high: float, low: float, close: float) -> dict:
    if isinstance(index, int) or str(index).isdigit():
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=int(index))
        stamp = ts.isoformat()
    else:
        stamp = str(index)
    return {"timestamp": stamp, "open": open_, "high": high, "low": low, "close": close, "volume": 1}


class FundingTests(unittest.TestCase):
    def test_enter_only_after_consecutive_rich_settlements(self) -> None:
        params = StrategyParams(funding_threshold_pct=0.005, funding_confirm_periods=3)
        rows = [
            {"timestamp": "2026-08-29T00:00:00+00:00", "close": 0.006},
            {"timestamp": "2026-08-29T08:00:00+00:00", "close": 0.007},
            {"timestamp": "2026-08-29T16:00:00+00:00", "close": 0.008},
        ]
        self.assertTrue(should_enter_carry(rows, params))
        rows[-1]["close"] = 0.001
        self.assertFalse(should_enter_carry(rows, params))

    def test_reverse_when_funding_is_stably_negative(self) -> None:
        from src.funding_strategy import carry_direction

        params = StrategyParams(funding_threshold_pct=0.01, funding_confirm_periods=2)
        rates = [-0.04, -0.05]
        self.assertEqual(carry_direction(rates, params), "reverse")
        self.assertEqual(carry_direction([0.02, 0.03], params), "carry")

    def test_exit_when_rate_flips_negative(self) -> None:
        self.assertTrue(should_exit_carry(-0.0001))
        self.assertFalse(should_exit_carry(0.0))
        self.assertFalse(should_exit_carry(0.01))

    def test_detect_cover_while_in_carry(self) -> None:
        funding = [{"timestamp": "2026-08-29T16:00:00+00:00", "close": -0.01}]
        price = [bar("2026-08-29T16:00:00+00:00", 100, 101, 99, 100)]
        signal = detect_funding_signal(
            funding,
            price,
            StrategyParams(funding_exit_confirm=1),
            in_carry=True,
            current_rate=-0.01,
        )
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "cover")

    def test_fee_filter_requires_funding_to_beat_four_taker_legs(self) -> None:
        from src.funding_strategy import funding_edge_covers_fees

        params = StrategyParams(funding_futures_maker=False)
        thin = [{"timestamp": "2026-08-29T00:00:00+00:00", "close": 0.005}] * 12
        rich = [{"timestamp": "2026-08-29T00:00:00+00:00", "close": -0.04}] * 12
        self.assertFalse(funding_edge_covers_fees(0.005, 4000.0, params, thin))
        self.assertTrue(funding_edge_covers_fees(-0.04, 4000.0, params, rich))

    def test_exit_needs_two_opposite_readings_when_confirm_is_2(self) -> None:
        from src.funding_strategy import should_exit_hedge

        self.assertFalse(should_exit_hedge(-0.01, "carry", [-0.01], confirm=2))
        self.assertTrue(should_exit_hedge(-0.02, "carry", [-0.01, -0.02], confirm=2))

    def test_momentum_skips_decaying_rate(self) -> None:
        from src.funding_strategy import abs_rate_rising

        self.assertTrue(abs_rate_rising([-0.03, -0.04]))
        self.assertFalse(abs_rate_rising([-0.04, -0.03]))

    def test_skip_near_settlement_unless_rate_is_strong(self) -> None:
        from src.funding_strategy import skip_near_settlement

        params = StrategyParams(funding_skip_minutes_before_settle=60, funding_strong_rate_pct=0.02)
        self.assertTrue(skip_near_settlement("2026-08-29T07:00:00+00:00", -0.01, params))
        self.assertFalse(skip_near_settlement("2026-08-29T08:00:00+00:00", -0.01, params))
        self.assertFalse(skip_near_settlement("2026-08-29T07:00:00+00:00", -0.04, params))

    def test_maker_futures_cut_round_trip_fees(self) -> None:
        from src.funding_strategy import round_trip_fees

        taker = StrategyParams(funding_futures_maker=False)
        maker = StrategyParams(funding_futures_maker=True)
        price = 4000.0
        self.assertGreater(round_trip_fees(price, taker), round_trip_fees(price, maker))

    def test_times_display_in_asia_kolkata(self) -> None:
        from src.config import format_ist

        self.assertEqual(
            format_ist("2026-08-29T00:00:00+00:00"),
            "2026-08-29 05:30:00 IST",
        )


class SymbolSizingTests(unittest.TestCase):
    def test_each_book_maps_to_its_own_inr_spot_pair(self) -> None:
        from src.config import symbol_spec

        self.assertEqual(symbol_spec("ETHUSD").spot, "ETH_INR")
        self.assertEqual(symbol_spec("BTCUSD").spot, "BTC_INR")
        self.assertEqual(symbol_spec("btcusd").contract_value, 0.001)

    def test_unknown_symbol_falls_back_to_one_unit_per_lot(self) -> None:
        from src.config import symbol_spec

        spec = symbol_spec("DOGEUSD")
        self.assertEqual(spec.spot, "DOGE_INR")
        self.assertEqual(spec.contract_value, 1.0)

    def test_lots_are_sized_so_books_carry_equal_notional(self) -> None:
        from src.config import lots_for_notional

        self.assertEqual(lots_for_notional("ETHUSD", 2450.0, 2450.0), 100)
        self.assertEqual(lots_for_notional("BTCUSD", 78000.0, 2450.0), 31)
        self.assertEqual(lots_for_notional("XRPUSD", 1.40, 2450.0), 1750)

    def test_hedge_qty_follows_contract_value_not_eth(self) -> None:
        params = StrategyParams(position_lots=31, contract_value=0.001)
        self.assertAlmostEqual(params.hedge_qty(), 0.031)
        self.assertAlmostEqual(params.notional_usd(78000.0), 2418.0)

    def test_state_files_are_separate_per_symbol(self) -> None:
        from src.config import live_state_path

        eth = live_state_path("funding", "ETHUSD")
        btc = live_state_path("funding", "BTCUSD")
        self.assertNotEqual(eth, btc)
        self.assertTrue(eth.name.endswith("funding_ETHUSD_state.json"))

    def test_default_params_size_from_price_when_lots_omitted(self) -> None:
        from src.strategy import default_params

        params = default_params(symbol="BTCUSD", price=78000.0, notional_usd=2450.0)
        self.assertEqual(params.position_lots, 31)
        self.assertEqual(params.spot_symbol, "BTC_INR")
        self.assertAlmostEqual(params.contract_value, 0.001)


class FundingScreenTests(unittest.TestCase):
    def _rows(self, rates: list[float]) -> list[dict]:
        return [{"timestamp": f"2026-01-01T{i % 24:02d}:00:00+00:00", "close": r}
                for i, r in enumerate(rates)]

    def test_one_sided_book_passes_the_screen(self) -> None:
        from src.funding_strategy import screen_funding_history

        report = screen_funding_history(self._rows([-0.02] * 78 + [0.01] * 22), "ETHUSD")
        self.assertTrue(report.tradable)
        self.assertEqual(report.dominant, "negative")
        self.assertAlmostEqual(report.one_sided_share, 0.78)

    def test_coin_flip_book_is_rejected(self) -> None:
        from src.funding_strategy import screen_funding_history

        report = screen_funding_history(self._rows([-0.02] * 54 + [0.02] * 46), "SOLUSD")
        self.assertFalse(report.tradable)
        self.assertIn("churn", report.note)

    def test_empty_history_is_not_tradable(self) -> None:
        from src.funding_strategy import screen_funding_history

        self.assertFalse(screen_funding_history([], "NEWUSD").tradable)


if __name__ == "__main__":
    unittest.main()
