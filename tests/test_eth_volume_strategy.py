"""Unit tests for ETH India volume-bias + pullback rules."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from src.eth_volume_strategy import (
    Pullback,
    bias_from_volume,
    candle_side,
    decide_open_trade,
    day_limit_reached,
    first_confirmation,
    first_pullback,
    is_bias_window,
    is_confirmation_candle,
    is_entry_window,
    is_pullback_candle,
    measure_volume_bias,
    pullback_stop_loss,
    split_session_bars,
    stop_is_valid,
    target_price,
    trail_stop_price,
)
from src.timezone import india_calendar_day


def _bar(
    hour_utc: int,
    minute_utc: int,
    *,
    open_price: float,
    close: float,
    high: float | None = None,
    low: float | None = None,
    volume: float = 1.0,
    day: str = "2026-09-10",
) -> dict:
    high = high if high is not None else max(open_price, close)
    low = low if low is not None else min(open_price, close)
    ts = datetime(2026, 9, 10, hour_utc, minute_utc, tzinfo=timezone.utc).isoformat()
    if day != "2026-09-10":
        ts = f"{day}T{hour_utc:02d}:{minute_utc:02d}:00+00:00"
    return {
        "timestamp": ts,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class EthVolumeStrategyTests(unittest.TestCase):
    def test_should_tag_bullish_candle_as_buy_side(self) -> None:
        self.assertEqual(candle_side(_bar(4, 0, open_price=100, close=101)), "buy")

    def test_should_tag_bearish_candle_as_sell_side(self) -> None:
        self.assertEqual(candle_side(_bar(4, 0, open_price=100, close=99)), "sell")

    def test_should_choose_long_bias_when_buy_volume_is_higher(self) -> None:
        self.assertEqual(bias_from_volume(10, 3), "long")

    def test_should_choose_short_bias_when_sell_volume_is_higher(self) -> None:
        self.assertEqual(bias_from_volume(2, 8), "short")

    def test_should_return_no_bias_when_volume_is_tied(self) -> None:
        self.assertEqual(bias_from_volume(5, 5), "")

    def test_should_sum_buy_and_sell_volume_from_candle_bodies(self) -> None:
        rows = [
            _bar(4, 0, open_price=100, close=101, volume=4),
            _bar(4, 5, open_price=101, close=100, volume=1),
            _bar(4, 10, open_price=100, close=102, volume=2),
        ]
        bias = measure_volume_bias(rows)
        self.assertEqual(bias.buy_volume, 6)
        self.assertEqual(bias.sell_volume, 1)
        self.assertEqual(bias.side, "long")
        self.assertEqual(bias.label, "BUY")

    def test_should_treat_pre_7pm_ist_as_bias_window(self) -> None:
        # 13:25 UTC = 18:55 IST
        ts = datetime(2026, 9, 10, 13, 25, tzinfo=timezone.utc).isoformat()
        self.assertTrue(is_bias_window(ts, 19))
        self.assertFalse(is_entry_window(ts, 19))

    def test_should_treat_7pm_ist_as_entry_window(self) -> None:
        # 13:30 UTC = 19:00 IST
        ts = datetime(2026, 9, 10, 13, 30, tzinfo=timezone.utc).isoformat()
        self.assertFalse(is_bias_window(ts, 19))
        self.assertTrue(is_entry_window(ts, 19))

    def test_should_split_india_day_bars_at_entry_hour(self) -> None:
        rows = [
            _bar(13, 25, open_price=100, close=101, volume=5),
            _bar(13, 30, open_price=101, close=100, volume=9),
        ]
        day = india_calendar_day(rows[0]["timestamp"])
        bias_bars, entry_bars = split_session_bars(rows, day, 19)
        self.assertEqual(len(bias_bars), 1)
        self.assertEqual(len(entry_bars), 1)
        self.assertEqual(measure_volume_bias(bias_bars).side, "long")

    def test_should_detect_sell_candle_as_long_pullback(self) -> None:
        row = _bar(13, 35, open_price=110, close=108, high=111, low=107)
        self.assertTrue(is_pullback_candle(row, "long"))
        self.assertFalse(is_pullback_candle(row, "short"))

    def test_should_skip_failed_pullback_and_use_the_next_one(self) -> None:
        rows = [
            _bar(13, 30, open_price=111, close=109, high=112, low=108),
            _bar(13, 45, open_price=109, close=107, high=110, low=105),
        ]
        first = first_pullback(rows, "long")
        assert first is not None
        nxt = first_pullback(rows, "long", after_timestamp=first.timestamp)
        assert nxt is not None
        self.assertEqual(nxt.low, 105)
        self.assertIsNone(first_pullback(rows, "long", after_timestamp=nxt.timestamp))

    def test_should_use_first_pullback_only(self) -> None:
        rows = [
            _bar(13, 30, open_price=110, close=111),
            _bar(13, 35, open_price=111, close=109, high=112, low=108),
            _bar(13, 40, open_price=109, close=107, high=110, low=106),
        ]
        pullback = first_pullback(rows, "long")
        self.assertIsNotNone(pullback)
        assert pullback is not None
        self.assertEqual(pullback.low, 108)
        self.assertEqual(pullback_stop_loss(pullback, "long"), 108)

    def test_should_mark_short_stop_at_pullback_wick_high(self) -> None:
        rows = [_bar(13, 35, open_price=100, close=102, high=103.5, low=99.5)]
        pullback = first_pullback(rows, "short")
        self.assertIsNotNone(pullback)
        assert pullback is not None
        self.assertEqual(pullback_stop_loss(pullback, "short"), 103.5)

    def test_should_keep_wick_stop_at_one_percent(self) -> None:
        self.assertEqual(trail_stop_price("long", 1000.0, 990.0, 1.0), 990.0)
        self.assertEqual(trail_stop_price("short", 1000.0, 1010.0, 1.0), 1010.0)

    def test_should_ratchet_stop_from_two_to_four_percent(self) -> None:
        self.assertEqual(trail_stop_price("long", 1000.0, 990.0, 2.0), 1010.0)
        self.assertEqual(trail_stop_price("long", 1000.0, 990.0, 3.0), 1020.0)
        self.assertEqual(trail_stop_price("long", 1000.0, 990.0, 4.0), 1030.0)
        self.assertEqual(trail_stop_price("short", 1000.0, 1010.0, 2.0), 990.0)
        self.assertEqual(trail_stop_price("short", 1000.0, 1010.0, 3.0), 980.0)
        self.assertEqual(trail_stop_price("short", 1000.0, 1010.0, 4.0), 970.0)

    def test_should_set_five_percent_full_close_target(self) -> None:
        self.assertEqual(target_price("long", 1000.0), 1050.0)
        self.assertEqual(target_price("short", 1000.0), 950.0)

    def test_should_close_at_five_percent_before_trailing(self) -> None:
        action, stop = decide_open_trade("long", 1000.0, 990.0, 990.0, 1050.0, 1050.0)
        self.assertEqual(action, "take_profit")
        self.assertEqual(stop, 990.0)

    def test_should_hold_wick_stop_until_two_percent(self) -> None:
        action, stop = decide_open_trade("long", 1000.0, 990.0, 990.0, 1050.0, 1010.0)
        self.assertEqual(action, "hold")
        self.assertEqual(stop, 990.0)

    def test_should_trail_stop_to_one_percent_at_two_percent(self) -> None:
        action, stop = decide_open_trade("long", 1000.0, 990.0, 990.0, 1050.0, 1020.0)
        self.assertEqual(action, "trail")
        self.assertEqual(stop, 1010.0)

    def test_should_close_the_day_after_two_wins_or_two_losses(self) -> None:
        self.assertFalse(day_limit_reached(1, 1))
        self.assertTrue(day_limit_reached(2, 0))
        self.assertTrue(day_limit_reached(0, 2))

    def test_should_reject_stop_on_wrong_side_of_entry(self) -> None:
        self.assertTrue(stop_is_valid("long", 2500, 2494))
        self.assertFalse(stop_is_valid("long", 2500, 2501))
        self.assertTrue(stop_is_valid("short", 2500, 2506))
        self.assertFalse(stop_is_valid("short", 2500, 2499))

    def test_should_confirm_long_with_bullish_1m_candle(self) -> None:
        self.assertTrue(is_confirmation_candle(_bar(13, 46, open_price=2495, close=2498), "long"))
        self.assertFalse(is_confirmation_candle(_bar(13, 46, open_price=2495, close=2493), "long"))

    def test_should_ignore_1m_bars_inside_the_15m_pullback(self) -> None:
        pullback = Pullback(timestamp=_bar(13, 30, open_price=2502, close=2496)["timestamp"], high=2503, low=2490, close=2496)
        bars = [
            _bar(13, 44, open_price=2496, close=2499),
            _bar(13, 45, open_price=2496, close=2494),
            _bar(13, 46, open_price=2494, close=2498),
        ]
        confirm = first_confirmation(bars, pullback, "long", "15m")
        self.assertIsNotNone(confirm)
        assert confirm is not None
        self.assertEqual(confirm["timestamp"], bars[2]["timestamp"])


if __name__ == "__main__":
    unittest.main()
