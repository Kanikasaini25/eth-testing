from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.m15_liquidity import (
    GrabState,
    SwingPoint,
    find_swing_points,
    latest_unused_swing,
    process_m15_bar,
)


BASE = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)


def candle(offset_minutes: int, open_px: float, high: float, low: float, close: float) -> dict:
    stamp = (BASE + timedelta(minutes=offset_minutes)).isoformat()
    return {
        "timestamp": stamp,
        "open": open_px,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1.0,
    }


def swing(kind: str, pivot_minutes: int, confirm_minutes: int, price: float) -> SwingPoint:
    return SwingPoint(
        timestamp=(BASE + timedelta(minutes=pivot_minutes)).isoformat(),
        confirm_ts=(BASE + timedelta(minutes=confirm_minutes)).isoformat(),
        price=price,
        kind=kind,
    )


class FindSwingPointsTests(unittest.TestCase):
    def test_should_mark_fractal_high_and_low_when_neighbors_confirm(self) -> None:
        bars = [
            candle(0, 10, 11, 9, 10),
            candle(15, 10, 12, 8, 10),
            candle(30, 10, 20, 4, 10),
            candle(45, 10, 13, 7, 10),
            candle(60, 10, 12, 8, 10),
        ]
        swings = find_swing_points(bars, left=2, right=2)
        highs = [item for item in swings if item.kind == "high"]
        lows = [item for item in swings if item.kind == "low"]
        self.assertEqual(len(highs), 1)
        self.assertEqual(highs[0].price, 20)
        self.assertEqual(len(lows), 1)
        self.assertEqual(lows[0].price, 4)


class BuySetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.swings = [swing("low", 0, 30, 2400.0)]
        self.state = GrabState()

    def _process(self, row: dict):
        return process_m15_bar(
            row,
            self.swings,
            self.state,
            target_points=15,
            confirmation_window_bars=15,
        )

    def test_should_enter_buy_when_second_green_breaks_first_green_high(self) -> None:
        grab = self._process(candle(31, 2402, 2403, 2398, 2399))
        first = self._process(candle(32, 2399, 2404, 2398.5, 2403))
        signal = self._process(candle(33, 2403, 2408, 2402, 2407))

        self.assertIsNone(grab)
        self.assertIsNone(first)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.entry_price, 2404)
        self.assertEqual(signal.stop_loss, 2398.5)
        self.assertEqual(signal.target, 2419)
        self.assertEqual(signal.entry_line, "swing_low")

    def test_should_reset_buy_confirmation_when_a_red_candle_appears(self) -> None:
        self._process(candle(31, 2402, 2403, 2398, 2399))
        self._process(candle(32, 2399, 2404, 2398.5, 2403))
        reset = self._process(candle(33, 2403, 2404, 2399, 2400))
        self.assertIsNone(reset)
        self.assertIsNone(self.state.pending_green)

        self._process(candle(34, 2400, 2402, 2399.5, 2401.5))
        signal = self._process(candle(35, 2401.5, 2406, 2401, 2405))
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.entry_price, 2402)

    def test_should_not_enter_buy_when_second_green_does_not_break_first_high(self) -> None:
        self._process(candle(31, 2402, 2403, 2398, 2399))
        self._process(candle(32, 2399, 2405, 2398.5, 2404))
        signal = self._process(candle(33, 2404, 2404.5, 2403, 2404.2))
        self.assertIsNone(signal)
        self.assertIsNotNone(self.state.pending_green)
        assert self.state.pending_green is not None
        self.assertEqual(self.state.pending_green["high"], 2404.5)

    def test_should_allow_grab_candle_to_be_the_first_green(self) -> None:
        first = self._process(candle(31, 2399, 2403, 2397, 2402))
        signal = self._process(candle(32, 2402, 2406, 2401, 2405))
        self.assertIsNone(first)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.entry_price, 2403)

    def test_should_keep_first_green_when_later_bars_still_sweep_the_low(self) -> None:
        self._process(candle(31, 2402, 2403, 2398, 2399))
        self._process(candle(32, 2399, 2404, 2397, 2403))
        signal = self._process(candle(33, 2403, 2408, 2396, 2407))
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.entry_price, 2404)

    def test_should_skip_buy_when_stop_is_tighter_than_minimum(self) -> None:
        self._process(candle(31, 2402, 2403, 2398, 2399))
        self._process(candle(32, 2399, 2404, 2402.5, 2403.5))
        signal = process_m15_bar(
            candle(33, 2403.5, 2408, 2403, 2407),
            self.swings,
            self.state,
            target_points=15,
            confirmation_window_bars=15,
            min_sl_points=5.0,
            max_sl_points=10.0,
            min_reward_to_risk=1.5,
        )
        self.assertIsNone(signal)


class SellSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.swings = [swing("high", 0, 30, 2500.0)]
        self.state = GrabState()

    def _process(self, row: dict):
        return process_m15_bar(
            row,
            self.swings,
            self.state,
            target_points=15,
            confirmation_window_bars=15,
        )

    def test_should_enter_sell_when_second_red_breaks_first_red_low(self) -> None:
        self._process(candle(31, 2498, 2502, 2497, 2501))
        self._process(candle(32, 2501, 2503, 2496, 2497))
        signal = self._process(candle(33, 2497, 2498, 2493, 2494))
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertEqual(signal.entry_price, 2496)
        self.assertEqual(signal.stop_loss, 2503)
        self.assertEqual(signal.target, 2481)
        self.assertEqual(signal.entry_line, "swing_high")


class GrabWindowAndReuseTests(unittest.TestCase):
    def test_should_cancel_grab_when_confirmation_window_expires(self) -> None:
        swings = [swing("low", 0, 30, 2400.0)]
        state = GrabState()
        process_m15_bar(
            candle(31, 2402, 2403, 2398, 2399),
            swings,
            state,
            target_points=15,
            confirmation_window_bars=15,
        )
        self.assertEqual(state.grabbed_side, "down")
        signal = process_m15_bar(
            candle(47, 2405, 2406, 2404, 2405),
            swings,
            state,
            target_points=15,
            confirmation_window_bars=15,
        )
        self.assertIsNone(signal)
        self.assertIsNone(state.grabbed_side)

    def test_should_not_reuse_a_traded_swing_low(self) -> None:
        swings = [swing("low", 0, 30, 2400.0)]
        state = GrabState()
        process_m15_bar(
            candle(31, 2399, 2403, 2397, 2402),
            swings,
            state,
            target_points=15,
            confirmation_window_bars=15,
        )
        signal = process_m15_bar(
            candle(32, 2402, 2406, 2401, 2405),
            swings,
            state,
            target_points=15,
            confirmation_window_bars=15,
        )
        self.assertIsNotNone(signal)
        later = latest_unused_swing(
            swings,
            "low",
            state.used_swing_low_ts,
            candle(40, 2405, 2406, 2390, 2391)["timestamp"],
        )
        self.assertIsNone(later)


if __name__ == "__main__":
    unittest.main()
