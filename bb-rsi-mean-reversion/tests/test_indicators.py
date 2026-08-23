import unittest

from src.indicators import bollinger_bands, rsi_cutler, sma, snapshot
from src.strategy import evaluate_closed_candle, previous_hour_trend


def _bar(index: int, price: float, wick: float = 0.2) -> dict:
    minute = index % 60
    hour = index // 60
    return {
        "timestamp": f"2026-08-22T{hour:02d}:{minute:02d}:00+00:00",
        "open": price + 0.1,
        "high": price + wick,
        "low": price - wick,
        "close": price,
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

    def test_long_signal_requires_lower_band_and_rsi(self) -> None:
        candles = [_bar(index, 100.0) for index in range(60)]
        candles.append(_bar(60, 90.0, wick=1.0))
        signal = evaluate_closed_candle(candles)
        snap = snapshot([float(row["close"]) for row in candles])
        self.assertIsNotNone(snap)
        assert snap is not None
        self.assertLess(snap.rsi, 30)
        last = candles[-1]
        self.assertTrue(last["close"] <= snap.lower_band or last["low"] <= snap.lower_band)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "long")

    def test_short_signal_requires_upper_band_and_rsi(self) -> None:
        candles = [_bar(index, 100.0 + index * 0.25) for index in range(60)]
        candles.append(_bar(60, 130.0, wick=1.0))
        signal = evaluate_closed_candle(candles)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertGreater(signal.indicators.rsi, 70)

    def test_no_signal_when_rsi_not_extreme(self) -> None:
        candles = []
        price = 100.0
        for index in range(30):
            price += 0.05 if index % 2 == 0 else -0.04
            candles.append(
                {
                    "timestamp": f"2026-08-22T00:{index:02d}:00+00:00",
                    "open": price,
                    "high": price + 0.1,
                    "low": price - 0.1,
                    "close": price,
                    "volume": 1.0,
                }
            )
        self.assertIsNone(evaluate_closed_candle(candles))

    def test_long_is_blocked_after_1h_up_run(self) -> None:
        candles = [_bar(index, 90.0 + index * 0.4) for index in range(60)]
        candles.append(_bar(60, 90.0, wick=1.0))
        trend = previous_hour_trend(candles)
        self.assertIsNotNone(trend)
        assert trend is not None
        self.assertEqual(trend.direction, "up")
        self.assertIsNone(evaluate_closed_candle(candles))

    def test_reentry_fades_1h_without_rsi_extreme(self) -> None:
        candles = [_bar(index, 100.0 + index * 0.2) for index in range(60)]
        candles.append(_bar(60, 111.0, wick=0.2))
        self.assertIsNone(evaluate_closed_candle(candles))
        signal = evaluate_closed_candle(candles, after_session_stop=True)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.side, "short")
        self.assertIn("re-entry", signal.reason)


if __name__ == "__main__":
    unittest.main()
