from __future__ import annotations

from datetime import datetime


def passes_stop_filters(
    side: str,
    entry_price: float,
    stop_loss: float,
    *,
    target_points: float,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
) -> bool:
    if side == "long" and stop_loss >= entry_price:
        return False
    if side == "short" and stop_loss <= entry_price:
        return False
    distance = abs(entry_price - stop_loss)
    if min_sl_points > 0 and distance < min_sl_points:
        return False
    if max_sl_points > 0 and distance > max_sl_points:
        return False
    if min_reward_to_risk > 0 and distance > 0:
        if (target_points / distance) < min_reward_to_risk:
            return False
    return True


def in_utc_session(timestamp: str, start_hour: int, end_hour: int) -> bool:
    hour = int(timestamp[11:13])
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def entry_reward_points(stop_distance: float, min_target: float, reward_r: float) -> float:
    if reward_r <= 0:
        return min_target
    return max(min_target, stop_distance * reward_r)


def entry_target_price(side: str, entry_price: float, reward_points: float) -> float:
    if side == "long":
        return entry_price + reward_points
    return entry_price - reward_points


def trend_allows(side: str, trend: str) -> bool:
    if trend == "flat":
        return True
    if trend == "up":
        return side == "long"
    return side == "short"


def is_utc_monday(timestamp: str) -> bool:
    return datetime.fromisoformat(timestamp).weekday() == 0


def open_pullback_allows(side: str, fill: float, day_open: float | None) -> bool:
    if day_open is None:
        return True
    if side == "long":
        return fill <= day_open
    return fill >= day_open


def intraday_range_allows(
    day_high: float | None,
    day_low: float | None,
    max_range: float,
) -> bool:
    if max_range <= 0 or day_high is None or day_low is None:
        return True
    return (day_high - day_low) <= max_range


def fill_stop_allowed(fill: float, stop_loss: float, max_sl_points: float) -> bool:
    if max_sl_points <= 0:
        return True
    return abs(fill - stop_loss) <= max_sl_points
