from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.trade_filters import (
    entry_reward_points,
    entry_target_price,
    in_utc_session,
    intraday_range_allows,
    is_utc_monday,
    open_pullback_allows,
    passes_stop_filters,
    trend_allows,
)
from src.volume_profile import VolumeProfileLevels, build_fixed_range_profile

M15_SECONDS = 900


@dataclass
class SessionLevels:
    day: str
    poc: float
    val: float
    vah: float
    bias: str
    session_open: float
    session_close: float


@dataclass
class PocState:
    current_day: str = ""
    levels: SessionLevels | None = None
    used_levels: set[str] = field(default_factory=set)
    away_side: str | None = None
    day_open: float | None = None
    day_high: float | None = None
    day_low: float | None = None


@dataclass
class EntrySignal:
    side: str
    entry_price: float
    stop_loss: float
    target: float
    entry_line: str
    level: float


def bar_day(timestamp: str) -> str:
    return timestamp[:10]


def group_bars_by_day(rows: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(bar_day(row["timestamp"]), []).append(row)
    return grouped


def closed_bars(rows: list[dict], bar_seconds: int, now_epoch: float) -> list[dict]:
    closed: list[dict] = []
    for row in rows:
        start = datetime.fromisoformat(row["timestamp"]).timestamp()
        if start + bar_seconds <= now_epoch:
            closed.append(row)
    return closed


def previous_day_bias(levels: VolumeProfileLevels) -> str:
    if levels.session_close > levels.session_open:
        return "up"
    if levels.session_close < levels.session_open:
        return "down"
    return "flat"


def session_levels_from_bars(
    previous_day: str,
    previous_bars: list[dict],
    *,
    bin_size: float,
    value_area_pct: float,
) -> SessionLevels | None:
    profile = build_fixed_range_profile(
        previous_bars, bin_size=bin_size, value_area_pct=value_area_pct
    )
    if profile is None:
        return None
    return SessionLevels(
        day=previous_day,
        poc=profile.poc,
        val=profile.val,
        vah=profile.vah,
        bias=previous_day_bias(profile),
        session_open=profile.session_open,
        session_close=profile.session_close,
    )


def update_away_side(state: PocState, close: float, min_away_points: float) -> None:
    if state.levels is None or min_away_points <= 0:
        return
    poc = state.levels.poc
    if close >= poc + min_away_points:
        state.away_side = "above"
    elif close <= poc - min_away_points:
        state.away_side = "below"


def update_intraday(state: PocState, row: dict) -> None:
    high = float(row["high"])
    low = float(row["low"])
    open_px = float(row["open"])
    if state.day_open is None:
        state.day_open = open_px
    state.day_high = high if state.day_high is None else max(state.day_high, high)
    state.day_low = low if state.day_low is None else min(state.day_low, low)


def hydrate_away_side(state: PocState, rows: list[dict], min_away_points: float) -> None:
    for row in rows:
        update_intraday(state, row)
        update_away_side(state, float(row["close"]), min_away_points)


def _bullish_reaction(
    row: dict,
    level: float,
    *,
    min_sweep_points: float,
    min_close_beyond: float,
    min_body_points: float,
) -> bool:
    close = float(row["close"])
    open_px = float(row["open"])
    low = float(row["low"])
    return (
        low <= level - min_sweep_points
        and close >= level + min_close_beyond
        and close > open_px
        and (close - open_px) >= min_body_points
    )


def _bearish_reaction(
    row: dict,
    level: float,
    *,
    min_sweep_points: float,
    min_close_beyond: float,
    min_body_points: float,
) -> bool:
    close = float(row["close"])
    open_px = float(row["open"])
    high = float(row["high"])
    return (
        high >= level + min_sweep_points
        and close <= level - min_close_beyond
        and close < open_px
        and (open_px - close) >= min_body_points
    )


def _approach_allows(side: str, away_side: str | None, require_return: bool) -> bool:
    if not require_return:
        return True
    if side == "long":
        return away_side == "above"
    return away_side == "below"


def _level_price(levels: SessionLevels, name: str) -> float:
    return {"poc": levels.poc, "val": levels.val, "vah": levels.vah}[name]


def _candidate_levels(
    *,
    trade_poc: bool,
    trade_val: bool,
    trade_vah: bool,
) -> list[str]:
    names: list[str] = []
    if trade_poc:
        names.append("poc")
    if trade_val:
        names.append("val")
    if trade_vah:
        names.append("vah")
    return names


def _target_price(
    side: str,
    fill: float,
    stop_loss: float,
    levels: SessionLevels,
    min_target: float,
    reward_r: float,
) -> float:
    r_target = entry_target_price(
        side,
        fill,
        entry_reward_points(abs(fill - stop_loss), min_target, reward_r),
    )
    if side == "long":
        va_target = levels.vah if levels.vah > fill else r_target
        return max(r_target, va_target)
    va_target = levels.val if levels.val < fill else r_target
    return min(r_target, va_target)


def _try_signal(
    side: str,
    row: dict,
    levels: SessionLevels,
    name: str,
    *,
    min_target: float,
    reward_r: float,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
) -> EntrySignal | None:
    fill = float(row["close"])
    stop_loss = float(row["low"] if side == "long" else row["high"])
    target = _target_price(side, fill, stop_loss, levels, min_target, reward_r)
    reward = abs(target - fill)
    if not passes_stop_filters(
        side,
        fill,
        stop_loss,
        target_points=reward,
        min_sl_points=min_sl_points,
        max_sl_points=max_sl_points,
        min_reward_to_risk=min_reward_to_risk,
    ):
        return None
    return EntrySignal(
        side=side,
        entry_price=fill,
        stop_loss=stop_loss,
        target=target,
        entry_line=name,
        level=_level_price(levels, name),
    )


def sync_session_state(
    state: PocState,
    row_day: str,
    previous_day: str | None,
    previous_bars: list[dict] | None,
    *,
    bin_size: float,
    value_area_pct: float,
) -> None:
    if state.current_day == row_day:
        return
    state.current_day = row_day
    state.used_levels = set()
    state.away_side = None
    state.day_open = None
    state.day_high = None
    state.day_low = None
    if not previous_day or not previous_bars:
        state.levels = None
        return
    state.levels = session_levels_from_bars(
        previous_day,
        previous_bars,
        bin_size=bin_size,
        value_area_pct=value_area_pct,
    )


def process_m15_bar(
    row: dict,
    state: PocState,
    *,
    touch_points: float = 2.0,
    min_target: float = 15.0,
    reward_r: float = 2.0,
    min_sl_points: float = 5.0,
    max_sl_points: float = 10.0,
    min_reward_to_risk: float = 1.5,
    use_session_filter: bool = True,
    session_start_hour_utc: int = 8,
    session_end_hour_utc: int = 20,
    use_htf_bias: bool = True,
    trade_poc: bool = True,
    trade_val: bool = False,
    trade_vah: bool = False,
    require_return: bool = True,
    min_away_points: float = 12.0,
    min_sweep_points: float = 2.0,
    min_close_beyond: float = 2.0,
    min_body_points: float = 0.0,
    require_open_pullback: bool = True,
    max_intraday_range: float = 100.0,
    skip_monday: bool = True,
) -> EntrySignal | None:
    update_intraday(state, row)
    levels = state.levels
    if levels is None:
        return None
    in_session = (not use_session_filter) or in_utc_session(
        row["timestamp"], session_start_hour_utc, session_end_hour_utc
    )
    signal: EntrySignal | None = None
    skip_day = skip_monday and is_utc_monday(row["timestamp"])
    range_ok = intraday_range_allows(state.day_high, state.day_low, max_intraday_range)
    if in_session and not skip_day and range_ok:
        for name in _candidate_levels(
            trade_poc=trade_poc, trade_val=trade_val, trade_vah=trade_vah
        ):
            if name in state.used_levels:
                continue
            level = _level_price(levels, name)
            long_ok = _bullish_reaction(
                row,
                level,
                min_sweep_points=min_sweep_points,
                min_close_beyond=min_close_beyond,
                min_body_points=min_body_points,
            )
            short_ok = _bearish_reaction(
                row,
                level,
                min_sweep_points=min_sweep_points,
                min_close_beyond=min_close_beyond,
                min_body_points=min_body_points,
            )
            fill = float(row["close"])
            if require_open_pullback:
                long_ok = long_ok and open_pullback_allows("long", fill, state.day_open)
                short_ok = short_ok and open_pullback_allows("short", fill, state.day_open)
            if long_ok and _approach_allows("long", state.away_side, require_return):
                if not (use_htf_bias and not trend_allows("long", levels.bias)):
                    signal = _try_signal(
                        "long",
                        row,
                        levels,
                        name,
                        min_target=min_target,
                        reward_r=reward_r,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                    )
                    if signal is not None:
                        state.used_levels.add(name)
                        break
            if (
                short_ok
                and signal is None
                and _approach_allows("short", state.away_side, require_return)
            ):
                if not (use_htf_bias and not trend_allows("short", levels.bias)):
                    signal = _try_signal(
                        "short",
                        row,
                        levels,
                        name,
                        min_target=min_target,
                        reward_r=reward_r,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                    )
                    if signal is not None:
                        state.used_levels.add(name)
                        break
    update_away_side(state, float(row["close"]), min_away_points)
    return signal
