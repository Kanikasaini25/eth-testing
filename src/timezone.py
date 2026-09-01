from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

DELTA_EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")


def delta_candle_day(timestamp: str) -> str:
    """Return the UTC label of a candle from Delta's API."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).date().isoformat()


def to_delta_time(timestamp: str) -> datetime:
    """Convert an ISO timestamp from Delta's UTC API to India display time."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
    return parsed.astimezone(DELTA_EXCHANGE_TIMEZONE)


def format_delta_timestamp(timestamp: str) -> str:
    """Format a Delta candle timestamp in the canonical UTC timezone."""
    parsed = datetime.fromisoformat(timestamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
