import unittest
from datetime import datetime, timezone

from src.backtest import BacktestConfig, SimPosition, WARMUP, _resolve_exit, run_backtest
from src.session import can_open_new_trade
from src.tables import daily_rows, trade_rows


def _bar(index: int, price: float, hour: int = 7, wick: float = 0.2) -> dict:
    minute = index % 60
    day = index // 60
    stamp = datetime(2026, 8, 3 + day, hour, minute, tzinfo=timezone.utc)
    return {
        "timestamp": stamp.isoformat(),
        "open": price + 0.05,
        "high": price + wick,
        "low": price - wick,
        "close": price,
        "volume": 1.0,
    }


def _dump_then_reclaim() -> list[dict]:
    candles = [_bar(index, 100.0) for index in range(WARMUP)]
    candles.append(_bar(WARMUP, 90.0, wick=1.0))
    candles.append(_bar(WARMUP + 1, 92.0, wick=0.2))
    return candles


class BacktestTests(unittest.TestCase):
    def test_long_dump_creates_a_trade_at_london_open(self) -> None:
        result = run_backtest(_dump_then_reclaim(), symbol="ETHUSD", days=1)
        self.assertGreaterEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].side, "long")
        self.assertEqual(result.trades[0].lots, 100)
        trade = result.trades[0]
        self.assertGreater(trade.entry_fee, 0)
        self.assertGreater(trade.exit_fee, 0)
        self.assertAlmostEqual(
            trade.pnl_usd,
            trade.gross_pnl - trade.entry_fee - trade.exit_fee,
            places=4,
        )

    def test_no_entry_outside_london_us_session(self) -> None:
        candles = [_bar(index, 100.0, hour=4) for index in range(WARMUP)]
        candles.append(_bar(WARMUP, 90.0, hour=4, wick=1.0))
        candles.append(_bar(WARMUP + 1, 92.0, hour=4))
        self.assertFalse(can_open_new_trade(datetime(2026, 8, 3, 4, tzinfo=timezone.utc)))
        result = run_backtest(candles, symbol="ETHUSD", days=1)
        self.assertEqual(len(result.trades), 0)

    def test_daily_cap_blocks_fifth_entry(self) -> None:
        candles: list[dict] = []
        price = 100.0
        for index in range(80):
            if index < WARMUP:
                candles.append(_bar(index, 100.0))
                continue
            if index % 2 == 0:
                price = 90.0
            else:
                price = 100.0
            candles.append(_bar(index, price, wick=1.0 if price == 90.0 else 0.2))
        result = run_backtest(
            candles,
            symbol="ETHUSD",
            days=1,
            config=BacktestConfig(daily_trade_cap=4, take_profit_usd=5.0),
        )
        self.assertLessEqual(len(result.trades), 4)

    def test_trade_table_ends_with_grand_total(self) -> None:
        result = run_backtest(_dump_then_reclaim(), symbol="ETHUSD", days=1)
        rows = trade_rows(result)
        self.assertEqual(rows[-1]["Side"], "GRAND TOTAL")
        daily = daily_rows(result)
        self.assertEqual(daily[-1]["IST day"], "GRAND TOTAL")


def _long_position() -> SimPosition:
    return SimPosition(
        side="long",
        entry_price=100.0,
        lots=100,
        stop_price=96.5,
        take_profit_price=110.0,
        profit_lock_price=105.0,
        max_profit_price=120.0,
        contract_eth=0.01,
        entry_ts="2026-08-03T03:00:00+00:00",
        rsi=25.0,
        lower_band=90.0,
        upper_band=110.0,
    )


def _lock_on() -> BacktestConfig:
    return BacktestConfig(enable_trailing_lock=True)


class ProfitLockExitTests(unittest.TestCase):
    def test_same_bar_that_first_hits_lock_does_not_exit_at_5(self) -> None:
        position = _long_position()
        bar = {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5}
        self.assertIsNone(_resolve_exit(position, bar, _lock_on()))
        self.assertTrue(position.profit_locked)
        self.assertEqual(position.stop_price, 105.0)

    def test_same_bar_that_reaches_tp_takes_10_not_5(self) -> None:
        position = _long_position()
        bar = {"open": 100.0, "high": 111.0, "low": 99.0, "close": 110.0}
        exit_price, reason = _resolve_exit(position, bar, _lock_on())
        self.assertEqual(reason, "take_profit")
        self.assertEqual(exit_price, 110.0)

    def test_later_bar_exit_at_lock_if_price_comes_back(self) -> None:
        position = _long_position()
        _resolve_exit(
            position,
            {"open": 100.0, "high": 106.0, "low": 99.0, "close": 105.5},
            _lock_on(),
        )
        exit_price, reason = _resolve_exit(
            position,
            {"open": 105.5, "high": 105.8, "low": 104.8, "close": 105.0},
            _lock_on(),
        )
        self.assertEqual(reason, "profit_lock")
        self.assertEqual(exit_price, 105.0)


if __name__ == "__main__":
    unittest.main()
