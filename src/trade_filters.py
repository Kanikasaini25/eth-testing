from __future__ import annotations


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


def resolve_stop(
    side: str,
    confirmation_stop: float,
    grab_extreme: float | None,
    mode: str,
) -> float:
    if mode != "grab_extreme" or grab_extreme is None:
        return confirmation_stop
    if side == "long":
        return min(confirmation_stop, grab_extreme)
    return max(confirmation_stop, grab_extreme)


def sweep_depth(side: str, grab_level: float | None, grab_extreme: float | None) -> float:
    if grab_level is None or grab_extreme is None:
        return 0.0
    if side == "long":
        return grab_level - grab_extreme
    return grab_extreme - grab_level


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


def m15_trend(closed_m15: list[dict], lookback: int = 8) -> str:
    if lookback <= 0 or len(closed_m15) < lookback + 1:
        return "flat"
    start = float(closed_m15[-lookback - 1]["close"])
    end = float(closed_m15[-1]["close"])
    if end > start:
        return "up"
    if end < start:
        return "down"
    return "flat"


def trend_allows(side: str, trend: str) -> bool:
    if trend == "flat":
        return True
    if trend == "up":
        return side == "long"
    return side == "short"


def fill_stop_allowed(fill: float, stop_loss: float, max_sl_points: float) -> bool:
    if max_sl_points <= 0:
        return True
    return abs(fill - stop_loss) <= max_sl_points
