from __future__ import annotations

import unittest

from src.backtest import (
    _breaks_opposing_candle,
    _impulse_opposite_candle,
    _latest_rejection_wick_stop,
    _power_entry_price,
    _with_opposing_level,
)
from src.order_flow import (
    OrderFlowParams,
    OrderFlowSnapshot,
    aggressive_side,
    evaluate_liquidity_order_flow,
    is_side_dominant,
    normalize_public_trade,
    split_bar_volume,
    bar_unix_range,
    snapshot_from_bars,
    snapshot_from_trades,
)


def _bar(ts: str, open_: float, high: float, low: float, close: float, volume: float) -> dict:
    return {
        "timestamp": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


class OrderFlowTests(unittest.TestCase):
    def test_aggressive_side_uses_taker(self) -> None:
        self.assertEqual(aggressive_side({"buyer_role": "taker", "seller_role": "maker"}), "buy")
        self.assertEqual(aggressive_side({"buyer_role": "maker", "seller_role": "taker"}), "sell")
        self.assertEqual(aggressive_side({"r": "t"}), "buy")
        self.assertEqual(aggressive_side({"r": "m"}), "sell")
        self.assertEqual(aggressive_side({"side": "sell"}), "sell")

    def test_normalize_trade_converts_microseconds(self) -> None:
        trade = normalize_public_trade(
            {
                "size": 10,
                "timestamp": 1_700_000_000_000_000,
                "price": "2500.5",
                "buyer_role": "taker",
                "seller_role": "maker",
            }
        )
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade["side"], "buy")
        self.assertEqual(trade["size"], 10.0)
        self.assertEqual(trade["timestamp"], 1_700_000_000.0)

    def test_bar_unix_range_uses_1m_duration(self) -> None:
        start, end = bar_unix_range(_bar("2026-09-14T00:00:00+00:00", 100, 110, 100, 109, 1000))
        self.assertEqual(end - start, 60)

    def test_split_bar_volume_close_near_high_is_buy(self) -> None:
        buy, sell = split_bar_volume(
            _bar("2026-09-14T00:00:00+00:00", 100, 110, 100, 109, 1000)
        )
        self.assertGreater(buy, sell)
        self.assertAlmostEqual(buy + sell, 1000)

    def test_long_requires_buy_dominance(self) -> None:
        params = OrderFlowParams()
        strong = OrderFlowSnapshot(buy_volume=1800, sell_volume=900)
        weak = OrderFlowSnapshot(buy_volume=900, sell_volume=2500)
        self.assertTrue(is_side_dominant("long", strong, params))
        self.assertFalse(is_side_dominant("long", weak, params))
        self.assertTrue(is_side_dominant("short", weak, params))

    def test_evaluate_rejects_seller_pressure_on_long(self) -> None:
        bars = [
            _bar("2026-09-14T00:00:00+00:00", 100, 101, 99, 99.2, 1000),
            _bar("2026-09-14T00:01:00+00:00", 99.2, 99.4, 98.5, 98.6, 1000),
            _bar("2026-09-14T00:02:00+00:00", 2500, 2503, 2499, 2503, 2000),
            _bar("2026-09-14T00:03:00+00:00", 2503, 2506, 2502, 2506, 2000),
        ]
        # Make confirmation look like selling into green candles.
        bars[2]["close"] = 2499.2
        bars[2]["high"] = 2503
        bars[2]["low"] = 2499
        bars[3]["close"] = 2502.1
        bars[3]["high"] = 2506
        bars[3]["low"] = 2502
        allowed, reason = evaluate_liquidity_order_flow(
            side="long",
            bars=bars,
            signal_index=2,
            entry_index=3,
            params=OrderFlowParams(require_sweep_reversal=False, require_price_align=False),
        )
        self.assertFalse(allowed)
        self.assertIn("volume", reason.lower())

    def test_evaluate_allows_strong_long(self) -> None:
        bars = [
            _bar("2026-09-14T00:00:00+00:00", 100, 101, 99, 99.2, 800),
            _bar("2026-09-14T00:01:00+00:00", 99.2, 99.5, 98.8, 98.9, 800),
            _bar("2026-09-14T00:02:00+00:00", 2500, 2504, 2499, 2503.5, 2000),
            _bar("2026-09-14T00:03:00+00:00", 2503.5, 2508, 2503, 2507.5, 2200),
        ]
        allowed, reason = evaluate_liquidity_order_flow(
            side="long",
            bars=bars,
            signal_index=2,
            entry_index=3,
            params=OrderFlowParams(),
        )
        self.assertTrue(allowed, reason)

    def test_snapshot_from_trades_filters_window(self) -> None:
        trades = [
            {"timestamp": 100.0, "size": 10, "side": "buy"},
            {"timestamp": 130.0, "size": 5, "side": "sell"},
            {"timestamp": 200.0, "size": 40, "side": "buy"},
        ]
        snap = snapshot_from_trades(trades, 120.0, 180.0)
        self.assertEqual(snap.buy_volume, 0)
        self.assertEqual(snap.sell_volume, 5)

    def test_disabled_filter_always_passes(self) -> None:
        allowed, _ = evaluate_liquidity_order_flow(
            side="long",
            bars=[_bar("2026-09-14T00:00:00+00:00", 1, 1, 1, 1, 0)],
            signal_index=0,
            entry_index=0,
            params=OrderFlowParams(enabled=False),
        )
        self.assertTrue(allowed)

    def test_snapshot_from_bars_sums_split_volume(self) -> None:
        rows = [
            _bar("2026-09-14T00:00:00+00:00", 10, 12, 10, 12, 100),
            _bar("2026-09-14T00:01:00+00:00", 12, 13, 11, 11, 100),
        ]
        snap = snapshot_from_bars(rows)
        self.assertGreater(snap.total, 0)
        self.assertAlmostEqual(snap.total, 200)

    def test_long_requires_close_above_dump_red_not_chop_red(self) -> None:
        rows = [
            _bar("2026-09-13T08:39:00+00:00", 2496.45, 2496.55, 2486.60, 2488.70, 1),
            _bar("2026-09-13T08:44:00+00:00", 2493.45, 2493.45, 2491.20, 2491.90, 1),
            _bar("2026-09-13T08:45:00+00:00", 2491.90, 2492.95, 2491.35, 2492.05, 1),
            _bar("2026-09-13T08:46:00+00:00", 2492.05, 2494.30, 2491.45, 2494.30, 1),
        ]
        opposite = _impulse_opposite_candle(rows, 2, "long", lookback=15)
        self.assertIsNotNone(opposite)
        assert opposite is not None
        self.assertEqual(opposite["high"], 2496.55)
        signal = _with_opposing_level(
            {"high": 2492.95, "low": 2491.35, "close": 2492.05, "index": 2},
            rows,
            2,
            "long",
            15,
        )
        # 08:46 broke the tiny 08:44 red, but did not close above the 08:39 dump.
        self.assertFalse(_breaks_opposing_candle("long", 2494.30, 2491.45, 2494.30, signal))
        self.assertTrue(_breaks_opposing_candle("long", 2497.20, 2493.00, 2497.00, signal))
        self.assertEqual(_power_entry_price("long", signal, 2497.00, False), 2496.55)

    def test_stop_uses_sweep_rejection_wick(self) -> None:
        long_signal = {
            "high": 2363.45,
            "low": 2355.65,
            "opposing_high": 2370.8,
            "opposing_low": 2361.0,
        }
        short_signal = {
            "high": 2510.4,
            "low": 2504.0,
            "opposing_high": 2514.2,
            "opposing_low": 2506.0,
        }
        # Aug 23 long: SL is the 05:17 hammer wick, not confirmation low 2361.2.
        self.assertEqual(_latest_rejection_wick_stop("long", long_signal), 2355.65)
        self.assertEqual(_latest_rejection_wick_stop("short", short_signal), 2514.2)


if __name__ == "__main__":
    unittest.main()
