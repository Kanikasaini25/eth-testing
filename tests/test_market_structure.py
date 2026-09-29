from __future__ import annotations

import unittest

from src.backtest import sweep_signal_allowed
from src.market_structure import StructureParams, evaluate_structure, retests_fresh_extreme

PDH = 100.0
PARAMS = StructureParams(
    enabled=True,
    pivot_bars=1,
    min_trend_swings=2,
    retest_tolerance_points=0.5,
    retest_window_bars=3,
)


def _bars(highs_lows: list[tuple[float, float, float]]) -> list[dict]:
    """(high, low, close) per 1m bar on one UTC day; open is the previous close."""
    rows = []
    prev_close = highs_lows[0][2]
    for minute, (high, low, close) in enumerate(highs_lows):
        rows.append(
            {
                "timestamp": f"2026-09-14T10:{minute:02d}:00+00:00",
                "open": prev_close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1,
            }
        )
        prev_close = close
    return rows


# Break PDH, swing high 102, higher low 101, higher high 104.
UPTREND = [
    (99.0, 98.0, 98.5),
    (102.0, 99.0, 101.5),
    (101.8, 101.0, 101.2),
    (103.0, 101.2, 102.8),
    (104.0, 102.5, 103.5),
    (103.6, 102.0, 102.2),
]
CHOCH = [(102.3, 100.2, 100.4)]
RETEST = [(100.9, 100.3, 100.5)]


def _mirror(rows: list[tuple[float, float, float]]) -> list[tuple[float, float, float]]:
    return [(200.0 - low, 200.0 - high, 200.0 - close) for high, low, close in rows]


class MarketStructureTests(unittest.TestCase):
    def test_should_block_short_when_trend_keeps_making_higher_highs(self) -> None:
        rows = _bars(UPTREND)
        check = evaluate_structure("short", rows, len(rows) - 1, PDH, PARAMS)
        self.assertTrue(check.blocks_entry)
        self.assertIn("higher low 101.00", check.reason)

    def test_should_block_short_after_choch_until_retest(self) -> None:
        rows = _bars(UPTREND + CHOCH)
        check = evaluate_structure("short", rows, len(rows) - 1, PDH, PARAMS)
        self.assertTrue(check.blocks_entry)
        self.assertEqual(check.broken_level, 101.0)

    def test_should_allow_short_signal_on_retest_of_broken_higher_low(self) -> None:
        rows = _bars(UPTREND + CHOCH + RETEST)
        allowed, check = sweep_signal_allowed(
            side="short",
            rows=rows,
            index=len(rows) - 1,
            level=PDH,
            beyond_line=False,
            structure_params=PARAMS,
        )
        self.assertTrue(check.ready)
        self.assertTrue(allowed)
        self.assertEqual(check.break_index, len(UPTREND))

    def test_should_keep_plain_sweep_rules_when_no_trend(self) -> None:
        rows = _bars([(99.0, 98.0, 98.5), (100.8, 98.5, 99.4), (99.6, 99.0, 99.1)])
        allowed, check = sweep_signal_allowed(
            side="short",
            rows=rows,
            index=len(rows) - 1,
            level=PDH,
            beyond_line=True,
            structure_params=PARAMS,
        )
        self.assertFalse(check.trending)
        self.assertTrue(allowed)

    def test_should_do_nothing_when_filter_disabled(self) -> None:
        rows = _bars(UPTREND)
        check = evaluate_structure("short", rows, len(rows) - 1, PDH, StructureParams())
        self.assertFalse(check.blocks_entry)

    def test_should_mirror_for_long_below_previous_day_low(self) -> None:
        pdl = 200.0 - PDH
        blocked = _bars(_mirror(UPTREND))
        check = evaluate_structure("long", blocked, len(blocked) - 1, pdl, PARAMS)
        self.assertTrue(check.blocks_entry)
        self.assertIn("lower high 99.00", check.reason)

        ready = _bars(_mirror(UPTREND + CHOCH + RETEST))
        check = evaluate_structure("long", ready, len(ready) - 1, pdl, PARAMS)
        self.assertTrue(check.ready)
        self.assertEqual(check.broken_level, 99.0)


# ETHUSD 2026-09-28 UTC, PDL 2668.15: (time, open, high, low, close).
SEP28 = [
    ("01:50", 2651.85, 2657.2, 2647.65, 2656.25),
    ("01:57", 2660.65, 2662.0, 2655.0, 2655.0),
    ("02:08", 2650.2, 2655.05, 2649.1, 2654.4),
    ("02:14", 2660.3, 2661.6, 2659.0, 2660.05),
    ("02:22", 2653.5, 2653.6, 2651.3, 2652.15),
    ("02:33", 2649.55, 2650.55, 2648.3, 2648.9),
    ("02:39", 2650.15, 2650.5, 2648.1, 2650.3),
    ("05:34", 2640.2, 2640.7, 2637.85, 2639.05),
    ("05:38", 2639.3, 2639.65, 2634.05, 2634.45),
    ("05:39", 2634.45, 2636.65, 2634.15, 2635.65),
    ("05:40", 2635.65, 2639.35, 2634.9, 2639.35),
    ("05:45", 2650.05, 2651.65, 2648.45, 2648.85),
]
SEP28_PDL = 2668.15
FRESH = StructureParams(require_fresh_extreme=True, fresh_window_bars=3, fresh_tolerance_points=1.0)


def _sep28_rows() -> list[dict]:
    return [
        {
            "timestamp": f"2026-09-28T{hhmm}:00+00:00",
            "open": o,
            "high": h,
            "low": low,
            "close": c,
            "volume": 1,
        }
        for hhmm, o, h, low, c in SEP28
    ]


def _bar_at(rows: list[dict], hhmm: str) -> int:
    return next(i for i, row in enumerate(rows) if row["timestamp"][11:16] == hhmm)


class FreshExtremeRetestTests(unittest.TestCase):
    def test_should_skip_long_on_green_candle_without_new_lower_low(self) -> None:
        rows = _sep28_rows()
        self.assertFalse(
            retests_fresh_extreme("long", rows, _bar_at(rows, "02:39"), SEP28_PDL, FRESH)
        )

    def test_should_allow_long_when_new_lower_low_is_retested(self) -> None:
        rows = _sep28_rows()
        for hhmm in ("05:39", "05:40"):
            self.assertTrue(
                retests_fresh_extreme("long", rows, _bar_at(rows, hhmm), SEP28_PDL, FRESH),
                hhmm,
            )

    def test_should_skip_long_when_price_has_left_the_new_low(self) -> None:
        rows = _sep28_rows()
        self.assertFalse(
            retests_fresh_extreme("long", rows, _bar_at(rows, "05:45"), SEP28_PDL, FRESH)
        )

    def test_should_gate_sweep_signal_with_fresh_extreme_rule(self) -> None:
        rows = _sep28_rows()
        allowed, _ = sweep_signal_allowed(
            side="long",
            rows=rows,
            index=_bar_at(rows, "02:39"),
            level=SEP28_PDL,
            beyond_line=True,
            structure_params=FRESH,
        )
        self.assertFalse(allowed)

    def test_should_mirror_fresh_extreme_for_short(self) -> None:
        mirrored = [
            {**row, "high": 5000 - row["low"], "low": 5000 - row["high"]}
            for row in _sep28_rows()
        ]
        pdh = 5000 - SEP28_PDL
        self.assertTrue(
            retests_fresh_extreme("short", mirrored, _bar_at(mirrored, "05:39"), pdh, FRESH)
        )
        self.assertFalse(
            retests_fresh_extreme("short", mirrored, _bar_at(mirrored, "02:39"), pdh, FRESH)
        )


if __name__ == "__main__":
    unittest.main()
