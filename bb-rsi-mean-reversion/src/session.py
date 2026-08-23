"""IST session gates. New entries only at London open and US open."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.config import (
    LONDON_OPEN_END_MIN_IST,
    LONDON_OPEN_START_MIN_IST,
    US_OPEN_END_MIN_IST,
    US_OPEN_START_MIN_IST,
)

IST = timezone(timedelta(hours=5, minutes=30))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_ist(moment: datetime | None = None) -> datetime:
    return (moment or utc_now()).astimezone(IST)


def _ist_minutes(moment: datetime | None = None) -> int:
    stamp = to_ist(moment)
    return stamp.hour * 60 + stamp.minute


def trading_day(moment: datetime | None = None) -> str:
    return to_ist(moment).strftime("%Y-%m-%d")


def utc_day(moment: datetime | None = None) -> str:
    return trading_day(moment)


def next_session_open(moment: datetime | None = None) -> datetime:
    stamp = to_ist(moment)
    hour, minute = divmod(LONDON_OPEN_START_MIN_IST, 60)
    today_open = stamp.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if stamp < today_open:
        return today_open
    tomorrow = stamp.date() + timedelta(days=1)
    return datetime(tomorrow.year, tomorrow.month, tomorrow.day, hour, minute, tzinfo=IST)


def next_ist_midnight(moment: datetime | None = None) -> datetime:
    return next_session_open(moment)


def next_utc_midnight(moment: datetime | None = None) -> datetime:
    return next_session_open(moment)


def is_london_open(moment: datetime | None = None) -> bool:
    minutes = _ist_minutes(moment)
    return LONDON_OPEN_START_MIN_IST <= minutes < LONDON_OPEN_END_MIN_IST


def is_us_open(moment: datetime | None = None) -> bool:
    minutes = _ist_minutes(moment)
    return US_OPEN_START_MIN_IST <= minutes < US_OPEN_END_MIN_IST


def is_entry_session(moment: datetime | None = None) -> bool:
    return is_london_open(moment) or is_us_open(moment)


def is_asian_session(moment: datetime | None = None) -> bool:
    return is_entry_session(moment)


def can_open_new_trade(moment: datetime | None = None) -> bool:
    return is_entry_session(moment)


def session_label(moment: datetime | None = None) -> str:
    if is_london_open(moment):
        return "LONDON_OPEN"
    if is_us_open(moment):
        return "US_OPEN"
    return "OUTSIDE"


def session_key(moment: datetime | None = None) -> str:
    """One key per IST day + open (London vs US). Empty when outside."""
    stamp = moment or utc_now()
    label = session_label(stamp)
    if label == "OUTSIDE":
        return ""
    return f"{trading_day(stamp)}:{label}"


def candle_is_closed(timestamp_iso: str, now: datetime | None = None) -> bool:
    bar_time = parse_bar_time(timestamp_iso)
    return bar_time.timestamp() + 60 <= (now or utc_now()).timestamp()


def parse_bar_time(timestamp_iso: str) -> datetime:
    bar_time = datetime.fromisoformat(timestamp_iso)
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    return bar_time.astimezone(timezone.utc)


def format_ist_clock(timestamp_iso: str) -> str:
    if not timestamp_iso:
        return ""
    return parse_bar_time(timestamp_iso).astimezone(IST).strftime("%Y-%m-%d %H:%M")


def in_loss_cooldown(last_loss_ts: str, now: datetime, minutes: int) -> bool:
    """True until `minutes` have passed since the last losing exit."""
    if not last_loss_ts or minutes <= 0:
        return False
    lost_at = parse_bar_time(last_loss_ts)
    return now < lost_at + timedelta(minutes=minutes)
