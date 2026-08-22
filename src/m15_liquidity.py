from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.trade_filters import (
    entry_reward_points,
    entry_target_price,
    in_utc_session,
    passes_stop_filters,
    resolve_stop,
    sweep_depth,
)

M15_SECONDS = 900
M1_SECONDS = 60


@dataclass
class SwingPoint:
    timestamp: str
    confirm_ts: str
    price: float
    kind: str


@dataclass
class GrabState:
    grabbed_side: str | None = None
    grab_level: float | None = None
    grab_ts: str = ""
    grab_swing_ts: str = ""
    pending_green: dict | None = None
    pending_red: dict | None = None
    used_swing_high_ts: str = ""
    used_swing_low_ts: str = ""
    grab_extreme: float | None = None


@dataclass
class EntrySignal:
    side: str
    entry_price: float
    stop_loss: float
    target: float
    entry_line: str
    grab_level: float
    grab_extreme: float = 0.0


def is_green(row: dict) -> bool:
    return float(row["close"]) > float(row["open"])


def is_red(row: dict) -> bool:
    return float(row["close"]) < float(row["open"])


def _ts_epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()


def closed_bars(rows: list[dict], bar_seconds: int, now_epoch: float) -> list[dict]:
    closed: list[dict] = []
    for row in rows:
        bar_start = _ts_epoch(row["timestamp"])
        if bar_start + bar_seconds <= now_epoch:
            closed.append(row)
    return closed


def find_swing_points(
    bars: list[dict],
    left: int = 2,
    right: int = 2,
) -> list[SwingPoint]:
    """Confirmed fractal swings. A pivot needs `left` bars before and `right` bars after."""
    swings: list[SwingPoint] = []
    end = len(bars) - right
    for index in range(left, end):
        high = float(bars[index]["high"])
        low = float(bars[index]["low"])
        left_range = range(index - left, index)
        right_range = range(index + 1, index + right + 1)
        is_high = all(high > float(bars[j]["high"]) for j in left_range) and all(
            high >= float(bars[j]["high"]) for j in right_range
        )
        is_low = all(low < float(bars[j]["low"]) for j in left_range) and all(
            low <= float(bars[j]["low"]) for j in right_range
        )
        confirm_ts = bars[index + right]["timestamp"]
        if is_high:
            swings.append(
                SwingPoint(bars[index]["timestamp"], confirm_ts, high, "high")
            )
        if is_low:
            swings.append(
                SwingPoint(bars[index]["timestamp"], confirm_ts, low, "low")
            )
    return swings


def latest_unused_swing(
    swings: list[SwingPoint],
    kind: str,
    used_ts: str,
    as_of_ts: str,
) -> SwingPoint | None:
    matched = [
        swing
        for swing in swings
        if swing.kind == kind
        and swing.confirm_ts <= as_of_ts
        and (not used_ts or swing.timestamp > used_ts)
    ]
    if not matched:
        return None
    return matched[-1]


def current_swing_levels(
    swings: list[SwingPoint],
    as_of_ts: str,
) -> tuple[float | None, float | None]:
    high = latest_unused_swing(swings, "high", "", as_of_ts)
    low = latest_unused_swing(swings, "low", "", as_of_ts)
    return (
        high.price if high else None,
        low.price if low else None,
    )


def _candle_snapshot(row: dict) -> dict:
    return {
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "index_ts": row["timestamp"],
    }


def detect_liquidity_grab(
    row: dict,
    swing_high: SwingPoint | None,
    swing_low: SwingPoint | None,
    state: GrabState,
) -> None:
    high = float(row["high"])
    low = float(row["low"])
    timestamp = row["timestamp"]
    grabbed_down = (
        swing_low is not None
        and low < swing_low.price
        and timestamp >= swing_low.confirm_ts
    )
    grabbed_up = (
        swing_high is not None
        and high > swing_high.price
        and timestamp >= swing_high.confirm_ts
    )
    if grabbed_down and grabbed_up and swing_low is not None and swing_high is not None:
        down_penetration = swing_low.price - low
        up_penetration = high - swing_high.price
        if down_penetration >= up_penetration:
            grabbed_up = False
        else:
            grabbed_down = False

    if grabbed_down and swing_low is not None:
        _update_down_grab(state, swing_low, timestamp, low)
        return
    if grabbed_up and swing_high is not None:
        _update_up_grab(state, swing_high, timestamp, high)


def _update_down_grab(state: GrabState, swing_low: SwingPoint, timestamp: str, low: float) -> None:
    if state.grabbed_side == "down":
        state.grab_extreme = min(state.grab_extreme or low, low)
        return
    state.grabbed_side = "down"
    state.grab_level = swing_low.price
    state.grab_ts = timestamp
    state.grab_swing_ts = swing_low.timestamp
    state.grab_extreme = low
    state.pending_green = None
    state.pending_red = None


def _update_up_grab(state: GrabState, swing_high: SwingPoint, timestamp: str, high: float) -> None:
    if state.grabbed_side == "up":
        state.grab_extreme = max(state.grab_extreme or high, high)
        return
    state.grabbed_side = "up"
    state.grab_level = swing_high.price
    state.grab_ts = timestamp
    state.grab_swing_ts = swing_high.timestamp
    state.grab_extreme = high
    state.pending_green = None
    state.pending_red = None


def _grab_expired(state: GrabState, timestamp: str, window_bars: int) -> bool:
    if window_bars <= 0 or not state.grab_ts:
        return False
    elapsed_minutes = int((_ts_epoch(timestamp) - _ts_epoch(state.grab_ts)) / M1_SECONDS)
    return elapsed_minutes > window_bars


def _clear_grab(state: GrabState) -> None:
    state.grabbed_side = None
    state.grab_level = None
    state.grab_ts = ""
    state.grab_swing_ts = ""
    state.pending_green = None
    state.pending_red = None
    state.grab_extreme = None


def _try_entry(side: str, first: dict, state: GrabState, filters: dict) -> EntrySignal | None:
    confirm_stop = float(first["low"] if side == "long" else first["high"])
    entry_price = float(first["high"] if side == "long" else first["low"])
    stop_loss = resolve_stop(
        side, confirm_stop, state.grab_extreme, filters["stop_loss_mode"]
    )
    if sweep_depth(side, state.grab_level, state.grab_extreme) < filters["min_sweep_points"]:
        return None
    reward = entry_reward_points(
        abs(entry_price - stop_loss),
        filters["target_points"],
        filters["reward_r"],
    )
    if not passes_stop_filters(
        side,
        entry_price,
        stop_loss,
        target_points=reward,
        min_sl_points=filters["min_sl_points"],
        max_sl_points=filters["max_sl_points"],
        min_reward_to_risk=filters["min_reward_to_risk"],
    ):
        return None
    return EntrySignal(
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        target=entry_target_price(side, entry_price, reward),
        entry_line="swing_low" if side == "long" else "swing_high",
        grab_level=float(state.grab_level or 0.0),
        grab_extreme=float(state.grab_extreme or confirm_stop),
    )


def _long_confirmation(row: dict, state: GrabState, filters: dict) -> EntrySignal | None:
    if not is_green(row):
        state.pending_green = None
        return None
    first = state.pending_green
    broke = (
        first is not None
        and row["timestamp"] > first["index_ts"]
        and float(row["high"]) > float(first["high"])
    )
    if broke and filters["require_close_beyond"] and float(row["close"]) <= float(first["high"]):
        broke = False
    if first and broke:
        signal = _try_entry("long", first, state, filters)
        if signal is None:
            state.pending_green = _candle_snapshot(row)
            return None
        state.used_swing_low_ts = state.grab_swing_ts
        _clear_grab(state)
        return signal
    state.pending_green = _candle_snapshot(row)
    return None


def _short_confirmation(row: dict, state: GrabState, filters: dict) -> EntrySignal | None:
    if not is_red(row):
        state.pending_red = None
        return None
    first = state.pending_red
    broke = (
        first is not None
        and row["timestamp"] > first["index_ts"]
        and float(row["low"]) < float(first["low"])
    )
    if broke and filters["require_close_beyond"] and float(row["close"]) >= float(first["low"]):
        broke = False
    if first and broke:
        signal = _try_entry("short", first, state, filters)
        if signal is None:
            state.pending_red = _candle_snapshot(row)
            return None
        state.used_swing_high_ts = state.grab_swing_ts
        _clear_grab(state)
        return signal
    state.pending_red = _candle_snapshot(row)
    return None


def _confirmation_filters(
    *,
    target_points: float,
    require_close_beyond: bool,
    stop_loss_mode: str,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    min_sweep_points: float,
    reward_r: float,
) -> dict:
    return {
        "target_points": target_points,
        "require_close_beyond": require_close_beyond,
        "stop_loss_mode": stop_loss_mode,
        "min_sl_points": min_sl_points,
        "max_sl_points": max_sl_points,
        "min_reward_to_risk": min_reward_to_risk,
        "min_sweep_points": min_sweep_points,
        "reward_r": reward_r,
    }


def process_two_candle_confirmation(
    row: dict,
    state: GrabState,
    *,
    target_points: float,
    confirmation_window_bars: int,
    require_close_beyond: bool = True,
    stop_loss_mode: str = "first_confirmation_candle",
    min_sl_points: float = 0.0,
    max_sl_points: float = 0.0,
    min_reward_to_risk: float = 0.0,
    min_sweep_points: float = 0.0,
    reward_r: float = 0.0,
    use_session_filter: bool = False,
    session_start_hour_utc: int = 8,
    session_end_hour_utc: int = 20,
) -> EntrySignal | None:
    if not state.grabbed_side:
        return None
    if use_session_filter and not in_utc_session(
        row["timestamp"], session_start_hour_utc, session_end_hour_utc
    ):
        return None
    if _grab_expired(state, row["timestamp"], confirmation_window_bars):
        _clear_grab(state)
        return None
    filters = _confirmation_filters(
        target_points=target_points,
        require_close_beyond=require_close_beyond,
        stop_loss_mode=stop_loss_mode,
        min_sl_points=min_sl_points,
        max_sl_points=max_sl_points,
        min_reward_to_risk=min_reward_to_risk,
        min_sweep_points=min_sweep_points,
        reward_r=reward_r,
    )
    if state.grabbed_side == "down":
        return _long_confirmation(row, state, filters)
    return _short_confirmation(row, state, filters)


def process_m15_bar(
    row: dict,
    swings: list[SwingPoint],
    state: GrabState,
    *,
    target_points: float,
    confirmation_window_bars: int,
    require_close_beyond: bool = True,
    stop_loss_mode: str = "first_confirmation_candle",
    min_sl_points: float = 0.0,
    max_sl_points: float = 0.0,
    min_reward_to_risk: float = 0.0,
    min_sweep_points: float = 0.0,
    reward_r: float = 0.0,
    use_session_filter: bool = False,
    session_start_hour_utc: int = 8,
    session_end_hour_utc: int = 20,
) -> EntrySignal | None:
    as_of = row["timestamp"]
    if _grab_expired(state, as_of, confirmation_window_bars):
        _clear_grab(state)
    swing_high = latest_unused_swing(swings, "high", state.used_swing_high_ts, as_of)
    swing_low = latest_unused_swing(swings, "low", state.used_swing_low_ts, as_of)
    detect_liquidity_grab(row, swing_high, swing_low, state)
    return process_two_candle_confirmation(
        row,
        state,
        target_points=target_points,
        confirmation_window_bars=confirmation_window_bars,
        require_close_beyond=require_close_beyond,
        stop_loss_mode=stop_loss_mode,
        min_sl_points=min_sl_points,
        max_sl_points=max_sl_points,
        min_reward_to_risk=min_reward_to_risk,
        min_sweep_points=min_sweep_points,
        reward_r=reward_r,
        use_session_filter=use_session_filter,
        session_start_hour_utc=session_start_hour_utc,
        session_end_hour_utc=session_end_hour_utc,
    )


def grab_from_session_fields(
    *,
    grabbed_side: str | None,
    grab_level: float | None,
    grab_ts: str,
    grab_swing_ts: str,
    pending_green: dict | None,
    pending_red: dict | None,
    used_swing_high_ts: str,
    used_swing_low_ts: str,
    grab_extreme: float | None = None,
) -> GrabState:
    return GrabState(
        grabbed_side=grabbed_side,
        grab_level=grab_level,
        grab_ts=grab_ts,
        grab_swing_ts=grab_swing_ts,
        pending_green=pending_green,
        pending_red=pending_red,
        used_swing_high_ts=used_swing_high_ts,
        used_swing_low_ts=used_swing_low_ts,
        grab_extreme=grab_extreme,
    )
