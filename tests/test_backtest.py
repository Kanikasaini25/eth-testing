"""Unit tests for ETH volume-bias backtest P/L simulation."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.backtest import backtest_volume_bias, pnl_usd, resolve_exit


def _bar(hour: int, minute: int, open_price: float, close: float, **kwargs: float) -> dict:
    high = float(kwargs.get("high", max(open_price, close)))
    low = float(kwargs.get("low", min(open_price, close)))
    volume = float(kwargs.get("volume", 1.0))
    ts = datetime(2026, 9, 10, hour, minute, tzinfo=timezone.utc).isoformat()
    return {
        "timestamp": ts,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class VolumeBiasBacktestTests(unittest.TestCase):
    def test_should_compute_usd_pnl_from_points_and_lots(self) -> None:
        # 100 lots * 20 points * 0.01 ETH/lot = $20
        self.assertEqual(pnl_usd(20.0, 100), 20.0)

    def test_should_count_stop_when_stop_and_target_hit_same_bar(self) -> None:
        bars = [_bar(13, 40, 1000, 1000, high=1051, low=980)]
        exit_price, reason, _ts = resolve_exit("long", 990.0, 1050.0, bars, entry_price=1000.0)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(exit_price, 990.0)

    def test_should_book_take_profit_on_long_after_buy_volume_day(self) -> None:
        pullback_rows = [
            _bar(4, 0, 980, 990, volume=8),
            _bar(13, 30, 1002, 996, high=1003, low=990, volume=1),
        ]
        entry_rows = [
            _bar(13, 45, 996, 994, volume=1),
            _bar(13, 46, 994, 1000, volume=1),
            _bar(13, 47, 1000, 1050, high=1051, low=999, volume=1),
        ]
        result = backtest_volume_bias(pullback_rows, entry_rows, lots=100, starting_wallet=10000)
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.side, "long")
        self.assertEqual(trade.exit_reason, "take_profit")
        self.assertEqual(trade.pnl_usd, 50.0)
        self.assertEqual(result.total_pnl_usd, 50.0)
        self.assertEqual(result.wins, 1)

    def test_should_retry_next_pullback_after_stop_loss(self) -> None:
        pullback_rows = [
            _bar(4, 0, 980, 990, volume=8),
            _bar(13, 30, 1002, 996, high=1003, low=990, volume=1),
            _bar(13, 45, 996, 992, high=997, low=988, volume=1),
        ]
        entry_rows = [
            _bar(13, 45, 996, 994, volume=1),
            _bar(13, 46, 994, 1000, volume=1),
            _bar(13, 47, 1000, 995, high=1001, low=989, volume=1),
            _bar(14, 0, 992, 991, volume=1),
            _bar(14, 1, 991, 994, volume=1),
            _bar(14, 2, 994, 1050, high=1051, low=993, volume=1),
        ]
        result = backtest_volume_bias(pullback_rows, entry_rows, lots=100, starting_wallet=10000)
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.trades[0].exit_reason, "stop_loss")
        self.assertEqual(result.trades[1].exit_reason, "take_profit")
        self.assertEqual(result.wins, 1)
        self.assertEqual(result.losses, 1)

    def test_should_move_stop_to_one_percent_after_two_percent_run(self) -> None:
        bars = [
            _bar(13, 47, 1000, 1018, high=1021, low=1012),
            _bar(13, 48, 1018, 1008, high=1019, low=1008),
        ]
        exit_price, reason, _ts = resolve_exit("long", 990.0, 1050.0, bars, entry_price=1000.0)
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(exit_price, 1010.0)

    def test_should_stop_after_two_losses_even_if_another_pullback_exists(self) -> None:
        pullback_rows = [
            _bar(4, 0, 980, 990, volume=8),
            _bar(13, 30, 1002, 996, high=1003, low=990, volume=1),
            _bar(13, 45, 996, 992, high=997, low=988, volume=1),
            _bar(14, 0, 992, 988, high=993, low=980, volume=1),
        ]
        entry_rows = [
            _bar(13, 45, 996, 994, volume=1),
            _bar(13, 46, 994, 1000, volume=1),
            _bar(13, 47, 1000, 995, high=1001, low=989, volume=1),
            _bar(14, 0, 992, 991, volume=1),
            _bar(14, 1, 991, 1000, volume=1),
            _bar(14, 2, 1000, 995, high=1001, low=987, volume=1),
            _bar(14, 15, 988, 987, volume=1),
            _bar(14, 16, 987, 1000, volume=1),
            _bar(14, 17, 1000, 1050, high=1051, low=999, volume=1),
        ]
        result = backtest_volume_bias(pullback_rows, entry_rows, lots=100, starting_wallet=10000)
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.losses, 2)
        self.assertEqual(result.wins, 0)

    def test_should_stop_after_two_wins_even_if_another_pullback_exists(self) -> None:
        pullback_rows = [
            _bar(4, 0, 980, 990, volume=8),
            _bar(13, 30, 1002, 996, high=1003, low=990, volume=1),
            _bar(13, 45, 996, 992, high=997, low=988, volume=1),
            _bar(14, 0, 992, 988, high=993, low=980, volume=1),
        ]
        entry_rows = [
            _bar(13, 45, 996, 994, volume=1),
            _bar(13, 46, 994, 1000, volume=1),
            _bar(13, 47, 1000, 1050, high=1051, low=999, volume=1),
            _bar(14, 0, 992, 991, volume=1),
            _bar(14, 1, 991, 1000, volume=1),
            _bar(14, 2, 1000, 1050, high=1051, low=999, volume=1),
            _bar(14, 15, 988, 987, volume=1),
            _bar(14, 16, 987, 1000, volume=1),
            _bar(14, 17, 1000, 1050, high=1051, low=999, volume=1),
        ]
        result = backtest_volume_bias(pullback_rows, entry_rows, lots=100, starting_wallet=10000)
        self.assertEqual(len(result.trades), 2)
        self.assertEqual(result.wins, 2)
        self.assertEqual(result.losses, 0)

    def test_should_book_stop_on_short_after_sell_volume_day(self) -> None:
        pullback_rows = [
            _bar(4, 0, 2520, 2500, volume=9),
            _bar(13, 30, 2488, 2492, high=2495, low=2487, volume=1),
        ]
        entry_rows = [
            _bar(13, 45, 2492, 2493, volume=1),
            _bar(13, 46, 2493, 2490, volume=1),
            _bar(13, 47, 2490, 2494, high=2496, low=2489, volume=1),
        ]
        result = backtest_volume_bias(pullback_rows, entry_rows, lots=100, starting_wallet=10000)
        self.assertEqual(len(result.trades), 1)
        trade = result.trades[0]
        self.assertEqual(trade.side, "short")
        self.assertEqual(trade.exit_reason, "stop_loss")
        self.assertLess(trade.pnl_usd, 0)
        self.assertEqual(result.losses, 1)


if __name__ == "__main__":
    unittest.main()
