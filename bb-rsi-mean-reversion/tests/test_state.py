import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.config import TESTNET_REST_URL, TESTNET_WS_URL, Settings
from src.session import utc_now
from src.state import DailyTracker, OpenPosition


def _settings() -> Settings:
    return Settings(
        api_key="test",
        api_secret="test",
        rest_url=TESTNET_REST_URL,
        ws_url=TESTNET_WS_URL,
        symbol="ETHUSD",
        daily_trade_cap=4,
        daily_max_loss_usd=14.0,
        per_trade_stop_usd=3.50,
        take_profit_usd=10.0,
        profit_lock_usd=5.0,
        max_profit_usd=20.0,
        lots=100,
        fee_pct_per_side=0.05,
        trail_to_max_profit=False,
        enable_trailing_lock=True,
        net_of_fees=True,
        poll_seconds=10,
        dry_run=True,
        loss_cooldown_minutes=15,
        max_session_stops=2,
    )


def _long_position() -> OpenPosition:
    return OpenPosition(
        side="long",
        entry_price=3500.0,
        lots=70,
        stop_price=3495.0,
        take_profit_price=3514.0,
        profit_lock_price=3507.0,
        max_profit_price=3528.0,
        contract_eth=0.01,
        entry_ts=utc_now().isoformat(),
    )


class StateTests(unittest.TestCase):
    def test_four_losses_trip_kill_switch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DailyTracker(_settings(), path=Path(tmp) / "state.json")
            for _ in range(4):
                tracker.record_entry(_long_position())
                tracker.record_exit(exit_price=3495.0, pnl_usd=-3.50, reason="stop_loss")
            self.assertEqual(tracker.state.trades_taken, 4)
            self.assertTrue(tracker.state.kill_switch)
            self.assertFalse(tracker.can_take_trade())
            self.assertTrue(tracker.should_kill())

    def test_loss_blocks_reentry_for_15_minutes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DailyTracker(_settings(), path=Path(tmp) / "state.json")
            position = _long_position()
            position.entry_ts = "2026-08-22T07:10:00+00:00"
            tracker.record_entry(position)
            tracker.record_exit(
                exit_price=3495.0,
                pnl_usd=-3.50,
                reason="stop_loss",
                exit_ts="2026-08-22T07:11:00+00:00",
            )
            soon = datetime(2026, 8, 22, 7, 20, tzinfo=timezone.utc)
            later = datetime(2026, 8, 22, 7, 25, tzinfo=timezone.utc)
            self.assertTrue(tracker.in_loss_cooldown(soon))
            self.assertFalse(tracker.can_take_trade(soon))
            self.assertFalse(tracker.in_loss_cooldown(later))
            self.assertTrue(tracker.can_take_trade(later))

    def test_profit_blocks_same_session_but_allows_next_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DailyTracker(_settings(), path=Path(tmp) / "state.json")
            london = datetime(2026, 8, 22, 7, 15, tzinfo=timezone.utc)
            tracker.refresh_session(london)
            tracker.record_entry(_long_position())
            tracker.record_exit(
                exit_price=3514.0,
                pnl_usd=10.0,
                reason="take_profit",
                exit_ts=london.isoformat(),
            )
            still_london = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
            us_open = datetime(2026, 8, 22, 13, 40, tzinfo=timezone.utc)
            self.assertFalse(tracker.can_take_trade(still_london))
            self.assertTrue(tracker.can_take_trade(us_open))

    def test_two_stop_losses_block_rest_of_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DailyTracker(_settings(), path=Path(tmp) / "state.json")
            first = datetime(2026, 8, 22, 7, 10, tzinfo=timezone.utc)
            second = datetime(2026, 8, 22, 7, 30, tzinfo=timezone.utc)
            after = datetime(2026, 8, 22, 7, 50, tzinfo=timezone.utc)
            for stamp in (first, second):
                tracker.record_entry(_long_position())
                tracker.record_exit(
                    exit_price=3495.0,
                    pnl_usd=-3.50,
                    reason="stop_loss",
                    exit_ts=stamp.isoformat(),
                )
            self.assertEqual(tracker.state.session_sl_count, 2)
            self.assertFalse(tracker.can_take_trade(after))

    def test_fifth_trade_blocked_by_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tracker = DailyTracker(_settings(), path=Path(tmp) / "state.json")
            for _ in range(4):
                tracker.record_entry(_long_position())
                tracker.record_exit(exit_price=3514.0, pnl_usd=10.0, reason="take_profit")
            self.assertFalse(tracker.state.kill_switch)
            self.assertFalse(tracker.can_take_trade())


if __name__ == "__main__":
    unittest.main()
