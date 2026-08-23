import unittest
from datetime import datetime, timezone

from src.session import (
    IST,
    can_open_new_trade,
    format_ist_clock,
    in_loss_cooldown,
    is_entry_session,
    session_label,
    session_key,
    trading_day,
)


def _ist(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 8, 22, hour, minute, tzinfo=IST)


class SessionTests(unittest.TestCase):
    def test_entries_only_at_london_and_us_open(self) -> None:
        self.assertFalse(can_open_new_trade(_ist(12, 29)))
        self.assertTrue(can_open_new_trade(_ist(12, 30)))
        self.assertTrue(can_open_new_trade(_ist(13, 45)))
        self.assertFalse(can_open_new_trade(_ist(14, 0)))
        self.assertFalse(can_open_new_trade(_ist(15)))
        self.assertFalse(can_open_new_trade(_ist(18, 30)))
        self.assertTrue(can_open_new_trade(_ist(19, 0)))
        self.assertTrue(can_open_new_trade(_ist(20, 0)))
        self.assertTrue(can_open_new_trade(_ist(21, 29)))
        self.assertFalse(can_open_new_trade(_ist(21, 30)))
        self.assertFalse(can_open_new_trade(_ist(22)))
        self.assertFalse(can_open_new_trade(_ist(0, 14)))

    def test_session_labels_are_opens_only(self) -> None:
        self.assertEqual(session_label(_ist(12, 30)), "LONDON_OPEN")
        self.assertEqual(session_label(_ist(19, 15)), "US_OPEN")
        self.assertEqual(session_label(_ist(15)), "OUTSIDE")

    def test_london_and_us_are_separate_session_keys(self) -> None:
        self.assertNotEqual(session_key(_ist(13)), session_key(_ist(20)))
        self.assertTrue(session_key(_ist(13)).endswith("LONDON_OPEN"))
        self.assertTrue(session_key(_ist(20)).endswith("US_OPEN"))
        self.assertEqual(session_key(_ist(15)), "")

    def test_trading_day_is_ist_calendar(self) -> None:
        self.assertEqual(trading_day(_ist(13)), "2026-08-22")
        utc_evening = datetime(2026, 8, 22, 20, 0, tzinfo=timezone.utc)
        self.assertEqual(trading_day(utc_evening), "2026-08-23")

    def test_ist_clock_matches_india_chart(self) -> None:
        stamp = "2026-08-20T18:44:00+00:00"
        self.assertEqual(format_ist_clock(stamp), "2026-08-21 00:14")
        self.assertFalse(is_entry_session(datetime.fromisoformat(stamp)))

    def test_loss_cooldown_is_15_minutes(self) -> None:
        lost = "2026-08-22T07:00:00+00:00"
        self.assertTrue(
            in_loss_cooldown(lost, datetime(2026, 8, 22, 7, 14, tzinfo=timezone.utc), 15)
        )
        self.assertFalse(
            in_loss_cooldown(lost, datetime(2026, 8, 22, 7, 15, tzinfo=timezone.utc), 15)
        )


if __name__ == "__main__":
    unittest.main()
