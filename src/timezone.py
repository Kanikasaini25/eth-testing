"""India Standard Time helpers. Candles are India-live, so every timestamp is IST."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, time, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30), "IST")
IST_LABEL = "IST (UTC+5:30)"


def today_ist() -> date_type:
    return datetime.now(IST).date()


def ist_day_start_epoch(day: date_type) -> int:
    """Midnight IST on `day`, as a Unix epoch."""
    return int(datetime.combine(day, time.min, tzinfo=IST).timestamp())


def ist_day_end_epoch(day: date_type) -> int:
    """End of `day` in IST, clamped to now so we never ask for future candles."""
    end = int(datetime.combine(day, time.max, tzinfo=IST).timestamp())
    return min(end, int(datetime.now(IST).timestamp()))


def epoch_to_ist_iso(epoch_seconds: float) -> str:
    """ISO-8601 with the +05:30 offset, so downstream parsing stays unambiguous."""
    return datetime.fromtimestamp(epoch_seconds, tz=IST).isoformat()


def to_ist(timestamp: str) -> datetime:
    return datetime.fromisoformat(timestamp).astimezone(IST)


def ist_display(timestamp: str, with_seconds: bool = False) -> str:
    """Short, human-readable IST stamp for tables and logs."""
    if not timestamp:
        return ""
    fmt = "%Y-%m-%d %H:%M:%S" if with_seconds else "%Y-%m-%d %H:%M"
    return to_ist(timestamp).strftime(fmt)


def now_ist_display() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S IST")
