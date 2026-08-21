from __future__ import annotations

FIXED_ENTRY_LOTS = 100
PARTIAL_EXIT_LOTS = 80
RUNNER_LOTS = 20


def _swing_high_before(daily_rows: list[dict], day: str, lookback: int) -> float:
    highs: list[float] = []
    for row in daily_rows:
        if row["timestamp"][:10] >= day:
            break
        highs.append(float(row["high"]))
    if not highs:
        return 0.0
    window = highs[-lookback:] if len(highs) >= lookback else highs
    return max(window)


def _swing_low_before(daily_rows: list[dict], day: str, lookback: int) -> float:
    lows: list[float] = []
    for row in daily_rows:
        if row["timestamp"][:10] >= day:
            break
        lows.append(float(row["low"]))
    if not lows:
        return 0.0
    window = lows[-lookback:] if len(lows) >= lookback else lows
    return min(window)


def _daily_liquidity_levels(daily_rows: list[dict]) -> dict[str, dict[str, float]]:
    levels: dict[str, dict[str, float]] = {}
    for index in range(1, len(daily_rows)):
        day = daily_rows[index]["timestamp"][:10]
        previous = daily_rows[index - 1]
        levels[day] = {
            "upper": float(previous["high"]),
            "lower": float(previous["low"]),
        }
    return levels


def _points_target(entry: float, side: str, points: float) -> float:
    if side == "long":
        return entry + points
    return entry - points


def _signal_body_ratio(open_price: float, high: float, low: float, close: float) -> float:
    candle_range = high - low
    if candle_range <= 0:
        return 0.0
    return abs(close - open_price) / candle_range


def _liquidity_entry_valid(
    side: str,
    entry_price: float,
    stop_loss: float,
    reward_points: float,
    *,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    max_sl_pct: float,
) -> bool:
    sl_distance = abs(entry_price - stop_loss)
    if min_sl_points > 0 and sl_distance < min_sl_points:
        return False
    if max_sl_points > 0 and sl_distance > max_sl_points:
        return False
    if min_reward_to_risk > 0 and sl_distance > 0:
        if (reward_points / sl_distance) < min_reward_to_risk:
            return False
    sl_pct = (sl_distance / entry_price) * 100 if entry_price else 100.0
    if sl_pct > max_sl_pct:
        return False
    if side == "short" and stop_loss <= entry_price:
        return False
    if side == "long" and stop_loss >= entry_price:
        return False
    return True


def _in_utc_session(timestamp: str, start_hour: int, end_hour: int) -> bool:
    hour = int(timestamp[11:13])
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _previous_daily_candle(daily_rows: list[dict], day: str) -> dict | None:
    for index in range(1, len(daily_rows)):
        if daily_rows[index]["timestamp"][:10] == day:
            return daily_rows[index - 1]
    return None


def _daily_trend_allows(side: str, daily_rows: list[dict], day: str) -> bool:
    previous = _previous_daily_candle(daily_rows, day)
    if previous is None:
        return True
    prev_open = float(previous["open"])
    prev_close = float(previous["close"])
    if side == "short":
        return prev_close < prev_open
    return prev_close > prev_open


def _liquidity_sweep_at_upper(high: float, close: float, upper: float) -> bool:
    return high > upper and close < upper


def _liquidity_sweep_at_lower(low: float, close: float, lower: float) -> bool:
    return low < lower and close > lower


def _liquidity_targets(
    side: str,
    entry_price: float,
    daily_rows: list[dict],
    day: str,
    *,
    use_swing_target_for_partial: bool,
    partial_target_points: float,
    swing_lookback: int,
    runner_swing_lookback: int,
) -> tuple[float, float, float]:
    """Return (target_1 partial, target_2 runner, reward_points in price)."""
    if use_swing_target_for_partial:
        if side == "short":
            target_1 = _swing_low_before(daily_rows, day, swing_lookback)
            target_2 = _swing_low_before(daily_rows, day, runner_swing_lookback)
            if target_2 > 0 and target_1 > 0 and target_2 >= target_1:
                target_2 = target_1 - max(abs(entry_price - target_1) * 0.5, 1.0)
            reward = max(entry_price - target_1, 0.0) if target_1 > 0 else 0.0
        else:
            target_1 = _swing_high_before(daily_rows, day, swing_lookback)
            target_2 = _swing_high_before(daily_rows, day, runner_swing_lookback)
            if target_2 > 0 and target_1 > 0 and target_2 <= target_1:
                target_2 = target_1 + max(abs(target_1 - entry_price) * 0.5, 1.0)
            reward = max(target_1 - entry_price, 0.0) if target_1 > 0 else 0.0
        return target_1, target_2, reward

    target_1 = _points_target(entry_price, side, partial_target_points)
    if side == "short":
        target_2 = _swing_low_before(daily_rows, day, swing_lookback)
    else:
        target_2 = _swing_high_before(daily_rows, day, swing_lookback)
    return target_1, target_2, partial_target_points


def _passes_liquidity_entry_filters(
    *,
    side: str,
    timestamp: str,
    entry_price: float,
    stop_loss: float,
    reward_points: float,
    daily_rows: list[dict],
    day: str,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    max_sl_pct: float,
    require_liquidity_sweep: bool = False,
    signal_high: float = 0.0,
    signal_low: float = 0.0,
    signal_close: float = 0.0,
    upper: float = 0.0,
    lower: float = 0.0,
    use_daily_trend_filter: bool = False,
    use_session_filter: bool = False,
    session_start_hour_utc: int = 8,
    session_end_hour_utc: int = 20,
) -> bool:
    if not _liquidity_entry_valid(
        side,
        entry_price,
        stop_loss,
        reward_points,
        min_sl_points=min_sl_points,
        max_sl_points=max_sl_points,
        min_reward_to_risk=min_reward_to_risk,
        max_sl_pct=max_sl_pct,
    ):
        return False
    if use_session_filter and not _in_utc_session(
        timestamp, session_start_hour_utc, session_end_hour_utc
    ):
        return False
    if use_daily_trend_filter and not _daily_trend_allows(side, daily_rows, day):
        return False
    if require_liquidity_sweep:
        if side == "short" and not _liquidity_sweep_at_upper(signal_high, signal_close, upper):
            return False
        if side == "long" and not _liquidity_sweep_at_lower(signal_low, signal_close, lower):
            return False
    return True
