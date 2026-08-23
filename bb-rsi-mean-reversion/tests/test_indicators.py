import unittest
from datetime import datetime, timezone

from src.indicators import bollinger_bands, rsi_cutler, sma
from src.strategy import evaluate_closed_candle


def _bar(
    hour: int,
    minute: int,
    *,
    open_px: float,
    close_px: float,
    low: float | None = None,
    high: float | None = None,
) -> dict:
    wick_high = max(open_px, close_px) + 0.2 if high is None else high
    wick_low = min(open_px, close_px) - 0.2 if low is None else low
    stamp = datetime(2026, 8, 3, hour, minute, tzinfo=timezone.utc)
    return {
        "timestamp": stamp.isoformat(),
        "open": open_px,
        "high": wick_high,
        "low": wick_low,
        "close": close_px,
        "volume": 1.0,
    }


class IndicatorTests(unittest.TestCase):
    def test_sma_is_simple_average(self) -> None:
        values = [1.0, 3.0, 5.0, 7.0]
        self.assertEqual(sma(values, 4), 4.0)
        self.assertIsNone(sma(values, 5))

    def test_bollinger_uses_sma_not_ema(self) -> None:
        closes = [10.0] * 20
        bands = bollinger_bands(closes, period=20, num_std=2.0)
        self.assertIsNotNone(bands)
        assert bands is not None
        middle, upper, lower, stdev = bands
        self.assertEqual(middle, 10.0)
        self.assertEqual(stdev, 0.0)
        self.assertEqual(upper, 10.0)
        self.assertEqual(lower, 10.0)

    def test_rsi_cutler_all_gains_is_100(self) -> None:
        closes = [float(index) for index in range(1, 16)]
        self.assertEqual(rsi_cutler(closes, period=14), 100.0)

    def test_rsi_cutler_all_losses_is_0(self) -> None:
        closes = [float(index) for index in range(16, 0, -1)]
        self.assertEqual(rsi_cutler(closes, period=14), 0.0)


class SessionPatternTests(unittest.TestCase):
    def test_london_two_reds_go_short_with_first_candle_high_stop(self) -> None:
        first = _bar(7, 0, open_px=100.0, close_px=99.4, low=99.2, high=100.3)
        second = _bar(7, 1, open_px=99.4, close_px=98.5, low=98.4)
        signal = evaluate_closed_candle([first, second])
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertEqual(signal.session, "LONDON")
        self.assertEqual(signal.stop_price, 100.3)

    def test_london_short_stop_is_first_red_high_not_low(self) -> None:
        first = _bar(7, 0, open_px=1906.50, close_px=1905.50, low=1905.05, high=1907.10)
        second = _bar(7, 1, open_px=1905.50, close_px=1904.80, low=1904.50, high=1905.80)
        signal = evaluate_closed_candle([first, second])
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertEqual(signal.stop_price, 1907.10)

    def test_london_retry_stop_is_one_tick_above_first_high(self) -> None:
        first = _bar(7, 0, open_px=100.0, close_px=99.4, low=99.2, high=100.3)
        second = _bar(7, 1, open_px=99.4, close_px=98.5, low=98.4)
        signal = evaluate_closed_candle([first, second], after_loss=True)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertEqual(signal.stop_price, 100.35)

    def test_london_skips_without_two_reds(self) -> None:
        first = _bar(7, 0, open_px=100.0, close_px=100.4)
        second = _bar(7, 1, open_px=100.4, close_px=99.5, low=99.4)
        self.assertIsNone(evaluate_closed_candle([first, second]))

    def test_us_two_greens_go_long_with_first_candle_low_stop(self) -> None:
        first = _bar(13, 30, open_px=100.0, close_px=100.6, low=99.8)
        second = _bar(13, 31, open_px=100.6, close_px=101.2, low=100.5)
        signal = evaluate_closed_candle([first, second])
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.session, "US")
        self.assertEqual(signal.stop_price, 99.8)

    def test_us_retry_stop_is_one_tick_below_first_low(self) -> None:
        first = _bar(13, 30, open_px=100.0, close_px=100.6, low=99.8)
        second = _bar(13, 31, open_px=100.6, close_px=101.2, low=100.5)
        signal = evaluate_closed_candle([first, second], after_loss=True)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")
        self.assertEqual(signal.stop_price, 99.75)

    def test_us_skips_without_two_greens(self) -> None:
        first = _bar(13, 30, open_px=100.0, close_px=99.4, low=99.2)
        second = _bar(13, 31, open_px=99.4, close_px=100.2, low=99.3)
        self.assertIsNone(evaluate_closed_candle([first, second]))

    def test_skips_when_bars_are_not_back_to_back(self) -> None:
        first = _bar(7, 0, open_px=100.0, close_px=99.4, low=99.2)
        second = _bar(7, 2, open_px=99.4, close_px=98.5, low=98.4)
        self.assertIsNone(evaluate_closed_candle([first, second]))

    def test_no_signal_outside_opens(self) -> None:
        first = _bar(4, 0, open_px=100.0, close_px=99.4, low=99.2)
        second = _bar(4, 1, open_px=99.4, close_px=98.5, low=98.4)
        self.assertIsNone(evaluate_closed_candle([first, second]))

    def test_london_two_greens_never_go_long(self) -> None:
        first = _bar(7, 0, open_px=100.0, close_px=100.6, low=99.8)
        second = _bar(7, 1, open_px=100.6, close_px=101.2, low=100.5)
        self.assertIsNone(evaluate_closed_candle([first, second]))

    def test_us_two_reds_never_go_short(self) -> None:
        first = _bar(13, 30, open_px=100.0, close_px=99.4, low=99.2)
        second = _bar(13, 31, open_px=99.4, close_px=98.5, low=98.4)
        self.assertIsNone(evaluate_closed_candle([first, second]))


if __name__ == "__main__":
    unittest.main()
