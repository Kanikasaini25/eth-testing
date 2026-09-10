from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DELTA_EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")


def parse_utc_timestamp(timestamp: str) -> datetime:
    """Parse a Delta ISO timestamp as UTC."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_delta_time(timestamp: str) -> datetime:
    """Convert an ISO timestamp from Delta's UTC API to India display time."""
    return parse_utc_timestamp(timestamp).astimezone(DELTA_EXCHANGE_TIMEZONE)


def india_now() -> datetime:
    """Current time in Asia/Kolkata."""
    return datetime.now(DELTA_EXCHANGE_TIMEZONE)


def india_calendar_day(timestamp: str) -> str:
    """India calendar day (YYYY-MM-DD) for a Delta candle timestamp."""
    return to_delta_time(timestamp).date().isoformat()


def india_today() -> str:
    """Current India calendar day (YYYY-MM-DD)."""
    return india_now().date().isoformat()


def format_india_timestamp(timestamp: str) -> str:
    """Format a Delta candle timestamp in India time."""
    return to_delta_time(timestamp).strftime("%Y-%m-%d %H:%M IST")
