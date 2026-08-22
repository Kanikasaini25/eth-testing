from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src.backtest import BacktestParams, OpenPosition, check_bar_exit, run_m15_backtest


BASE = datetime(2026, 8, 21, 10, 0, tzinfo=timezone.utc)


def bar(offset_minutes: int, open_px: float, high: float, low: float, close: float) -> dict:
    return {
        "timestamp": (BASE + timedelta(minutes=offset_minutes)).isoformat(),
        "open": open_px,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1.0,
    }


def swing_low_m15() -> list[dict]:
    return [
        bar(0, 2410, 2412, 2405, 2408),
        bar(15, 2408, 2409, 2402, 2404),
        bar(30, 2404, 2406, 2390, 2396),
        bar(45, 2396, 2405, 2395, 2402),
        bar(60, 2402, 2407, 2400, 2404),
        bar(75, 2404, 2410, 2401, 2406),
    ]


def grab_and_buy_m1() -> list[dict]:
    return [
        bar(75, 2404, 2405, 2403, 2404),
        bar(76, 2404, 2405, 2386, 2389),
        bar(77, 2389, 2396, 2388.5, 2395),
        bar(78, 2395, 2400, 2394, 2398),
        bar(79, 2398, 2420, 2397, 2418),
    ]


class CheckBarExitTests(unittest.TestCase):
    def test_should_take_profit_when_long_high_reaches_target(self) -> None:
        position = OpenPosition(
            side="long",
            entry_ts="t",
            entry_price=2398,
            stop_loss=2388.5,
            target=2413,
            lots=100,
            grab_level=2390,
            entry_line="swing_low",
        )
        reason, price = check_bar_exit(position, bar(79, 2398, 2414, 2397, 2413))
        self.assertEqual(reason, "take_profit")
        self.assertEqual(price, 2413)

    def test_should_use_stop_when_long_bar_hits_stop_and_target(self) -> None:
        position = OpenPosition(
            side="long",
            entry_ts="t",
            entry_price=2398,
            stop_loss=2388.5,
            target=2413,
            lots=100,
            grab_level=2390,
            entry_line="swing_low",
        )
        reason, price = check_bar_exit(position, bar(79, 2398, 2414, 2380, 2410))
        self.assertEqual(reason, "stop_loss")
        self.assertEqual(price, 2388.5)


class RunM15BacktestTests(unittest.TestCase):
    def test_should_take_profit_after_downside_grab_and_two_green_candles(self) -> None:
        params = BacktestParams(
            target_points=15,
            position_lots=100,
            fee_pct_per_side=0.0,
            starting_wallet_usd=10000,
            use_session_filter=False,
            min_sweep_points=3.0,
            reward_r_multiple=2.0,
            max_trades_per_day=6,
        )
        result = run_m15_backtest(swing_low_m15(), grab_and_buy_m1(), params)
        self.assertEqual(result.trade_count, 1)
        trade = result.trades[0]
        self.assertEqual(trade["side"], "long")
        self.assertEqual(trade["reason"], "take_profit")
        self.assertGreaterEqual(trade["points"], 15)
        self.assertGreater(result.net_pnl, 0)

    def test_should_skip_entries_during_warmup_days(self) -> None:
        params = BacktestParams(
            target_points=15,
            fee_pct_per_side=0.0,
            use_session_filter=False,
            warmup_days=10,
        )
        result = run_m15_backtest(swing_low_m15(), grab_and_buy_m1(), params)
        self.assertEqual(result.trade_count, 0)

    def test_should_size_lots_from_one_percent_risk(self) -> None:
        params = BacktestParams(
            target_points=15,
            position_lots=20,
            fee_pct_per_side=0.0,
            starting_wallet_usd=10000,
            use_session_filter=False,
            use_trend_filter=False,
            use_risk_sizing=True,
            risk_pct_per_trade=1.0,
            move_stop_to_breakeven=False,
            daily_loss_pct=0.0,
        )
        result = run_m15_backtest(swing_low_m15(), grab_and_buy_m1(), params)
        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0]["lots"], 10)

    def test_should_move_stop_to_breakeven_after_one_r(self) -> None:
        m1_rows = grab_and_buy_m1()[:-1] + [
            bar(79, 2398, 2408, 2396, 2406),
            bar(80, 2406, 2407, 2380, 2385),
        ]
        params = BacktestParams(
            target_points=15,
            fee_pct_per_side=0.0,
            use_session_filter=False,
            use_trend_filter=False,
            use_risk_sizing=False,
            position_lots=10,
            move_stop_to_breakeven=True,
            reward_r_multiple=2.0,
        )
        result = run_m15_backtest(swing_low_m15(), m1_rows, params)
        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0]["reason"], "stop_loss")
        self.assertEqual(result.trades[0]["exit_price"], 2398)

    def test_should_stop_out_when_price_breaks_first_green_low(self) -> None:
        m1_rows = grab_and_buy_m1()[:-1] + [bar(79, 2398, 2400, 2380, 2385)]
        params = BacktestParams(target_points=15, fee_pct_per_side=0.0, use_session_filter=False)
        result = run_m15_backtest(swing_low_m15(), m1_rows, params)
        self.assertEqual(result.trade_count, 1)
        self.assertEqual(result.trades[0]["reason"], "stop_loss")
        self.assertLess(result.net_pnl, 0)

    def _uptrend_short_setup(self) -> tuple[list[dict], list[dict]]:
        m15_rows = []
        for index in range(12):
            open_px = 1900.0 + index * 20
            close = open_px + 10
            high = close + 2
            low = open_px - 2
            if index == 7:
                high = 2200.0
            m15_rows.append(bar(index * 15, open_px, high, low, close))
        swing_high = float(m15_rows[7]["high"])
        m1_rows = [
            bar(180, swing_high - 2, swing_high + 6, swing_high - 3, swing_high + 4),
            bar(181, swing_high + 4, swing_high + 5, swing_high - 3, swing_high - 2),
            bar(182, swing_high - 2, swing_high - 1, swing_high - 5, swing_high - 4),
        ]
        return m15_rows, m1_rows

    def test_should_skip_short_when_15m_trend_is_up(self) -> None:
        m15_rows, m1_rows = self._uptrend_short_setup()
        allowed = BacktestParams(
            target_points=15,
            fee_pct_per_side=0.0,
            use_session_filter=False,
            use_trend_filter=False,
            min_sweep_points=3.0,
        )
        blocked = BacktestParams(
            target_points=15,
            fee_pct_per_side=0.0,
            use_session_filter=False,
            use_trend_filter=True,
            trend_lookback_bars=8,
            min_sweep_points=3.0,
        )
        self.assertEqual(run_m15_backtest(m15_rows, m1_rows, allowed).trade_count, 1)
        self.assertEqual(run_m15_backtest(m15_rows, m1_rows, blocked).trade_count, 0)

    def test_should_skip_when_fill_makes_stop_wider_than_max(self) -> None:
        m1_rows = [
            bar(75, 2404, 2405, 2403, 2404),
            bar(76, 2404, 2405, 2386, 2389),
            bar(77, 2389, 2396, 2388.5, 2395),
            bar(78, 2395, 2412, 2394, 2410),
        ]
        params = BacktestParams(
            target_points=15,
            fee_pct_per_side=0.0,
            use_session_filter=False,
            use_trend_filter=False,
            max_sl_points=10.0,
        )
        result = run_m15_backtest(swing_low_m15(), m1_rows, params)
        self.assertEqual(result.trade_count, 0)

    def test_should_return_no_trades_when_price_never_sweeps_a_swing(self) -> None:
        m1_rows = [bar(75 + index, 2404, 2405, 2403, 2404) for index in range(10)]
        result = run_m15_backtest(swing_low_m15(), m1_rows, BacktestParams())
        self.assertEqual(result.trade_count, 0)
        self.assertEqual(result.ending_wallet, 10000)


if __name__ == "__main__":
    unittest.main()
