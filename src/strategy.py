from __future__ import annotations

from dataclasses import dataclass

from src.swings import SwingPoint, latest_swing


@dataclass
class PendingSetup:
    side: str
    swing: SwingPoint
    grab_ts: str
    grab_epoch: float
    sweep_extreme: float
    first_confirm: dict | None = None
    failed: bool = False


@dataclass
class EntrySignal:
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    swing_price: float
    sweep_extreme: float
    grab_ts: str
    first_high: float
    first_low: float


def is_green(bar: dict) -> bool:
    return float(bar["close"]) > float(bar["open"])


def is_red(bar: dict) -> bool:
    return float(bar["close"]) < float(bar["open"])


def _candle_body(bar: dict) -> float:
    return abs(float(bar["close"]) - float(bar["open"]))


def detect_liquidity_grab(
    bar: dict,
    usable: list[SwingPoint],
    min_sweep_points: float = 1.0,
    require_close_back: bool = True,
) -> tuple[PendingSetup | None, list[SwingPoint]]:
    """A 15m wick through a swing that closes back is the grab. A close-through is a break, not a setup."""
    low = float(bar["low"])
    high = float(bar["high"])
    close = float(bar["close"])
    swing_low = latest_swing(usable, "low")
    swing_high = latest_swing(usable, "high")
    took_low = swing_low is not None and low < swing_low.price - min_sweep_points
    took_high = swing_high is not None and high > swing_high.price + min_sweep_points
    if took_low and took_high:
        taken = [item for item in (swing_low, swing_high) if item is not None]
        return None, taken
    if took_low and swing_low is not None:
        closed_back = close > swing_low.price
        if require_close_back and not closed_back:
            return None, [swing_low]
        setup = PendingSetup(
            side="long",
            swing=swing_low,
            grab_ts=bar["timestamp"],
            grab_epoch=0.0,
            sweep_extreme=low,
        )
        return setup, [swing_low]
    if took_high and swing_high is not None:
        closed_back = close < swing_high.price
        if require_close_back and not closed_back:
            return None, [swing_high]
        setup = PendingSetup(
            side="short",
            swing=swing_high,
            grab_ts=bar["timestamp"],
            grab_epoch=0.0,
            sweep_extreme=high,
        )
        return setup, [swing_high]
    return None, []


def update_sweep_extreme(setup: PendingSetup, bar: dict) -> None:
    low = float(bar["low"])
    high = float(bar["high"])
    if setup.side == "long":
        setup.sweep_extreme = min(setup.sweep_extreme, low)
        return
    setup.sweep_extreme = max(setup.sweep_extreme, high)


def _break_entry_price(
    first: dict,
    second: dict,
    side: str,
    *,
    require_close_break: bool,
) -> float | None:
    first_high = float(first["high"])
    first_low = float(first["low"])
    second_open = float(second["open"])
    second_high = float(second["high"])
    second_low = float(second["low"])
    second_close = float(second["close"])
    if side == "long":
        if require_close_break:
            return second_close if second_close > first_high else None
        if second_high <= first_high:
            return None
        return second_open if second_open > first_high else first_high
    if require_close_break:
        return second_close if second_close < first_low else None
    if second_low >= first_low:
        return None
    return second_open if second_open < first_low else first_low


def _stop_and_target(
    side: str,
    entry: float,
    sweep_extreme: float,
    target_points: float,
    sl_buffer: float,
    use_stop_loss: bool,
) -> tuple[float, float]:
    if side == "long":
        stop = sweep_extreme - sl_buffer if use_stop_loss else entry - 1_000_000
        return stop, entry + target_points
    stop = sweep_extreme + sl_buffer if use_stop_loss else entry + 1_000_000
    return stop, entry - target_points


def _entry_blocked(
    side: str,
    entry: float,
    stop: float,
    bar: dict,
    *,
    use_stop_loss: bool,
    max_sl_points: float,
) -> bool:
    if not use_stop_loss:
        return False
    risk = abs(entry - stop)
    if max_sl_points > 0 and risk > max_sl_points:
        return True
    if side == "long":
        return stop >= entry or float(bar["low"]) <= stop
    return stop <= entry or float(bar["high"]) >= stop


def _reclaimed_swing(side: str, entry: float, swing_price: float, require_reclaim: bool) -> bool:
    if not require_reclaim:
        return True
    if side == "long":
        return entry >= swing_price
    return entry <= swing_price


def setup_too_wide(setup: PendingSetup, max_sl_points: float, sl_buffer: float) -> bool:
    if max_sl_points <= 0:
        return False
    width = abs(setup.sweep_extreme - setup.swing.price) + sl_buffer
    return width > max_sl_points


def setup_invalidated(setup: PendingSetup, bar: dict) -> bool:
    close = float(bar["close"])
    if setup.side == "long":
        return close < setup.sweep_extreme
    return close > setup.sweep_extreme


def _reset_pair(setup: PendingSetup, bar: dict, one_shot: bool) -> None:
    setup.first_confirm = None if one_shot else bar


def confirm_entry(
    setup: PendingSetup,
    bar: dict,
    *,
    target_points: float,
    sl_buffer: float,
    use_stop_loss: bool,
    max_sl_points: float = 15.0,
    require_reclaim: bool = True,
    min_confirm_body: float = 1.5,
    require_close_break: bool = False,
    one_shot_confirm: bool = False,
) -> EntrySignal | None:
    """Two consecutive 1m reversal candles; enter when the second closes beyond the first."""
    reversal = is_green if setup.side == "long" else is_red
    if not reversal(bar) or _candle_body(bar) < min_confirm_body:
        if one_shot_confirm and setup.first_confirm is not None:
            setup.failed = True
        setup.first_confirm = None
        return None
    first = setup.first_confirm
    if first is None:
        setup.first_confirm = bar
        return None
    entry = _break_entry_price(
        first, bar, setup.side, require_close_break=require_close_break
    )
    if entry is None or not _reclaimed_swing(
        setup.side, entry, setup.swing.price, require_reclaim
    ):
        if one_shot_confirm:
            setup.failed = True
            setup.first_confirm = None
            return None
        _reset_pair(setup, bar, False)
        return None
    stop, target = _stop_and_target(
        setup.side, entry, setup.sweep_extreme, target_points, sl_buffer, use_stop_loss
    )
    if _entry_blocked(
        setup.side,
        entry,
        stop,
        bar,
        use_stop_loss=use_stop_loss,
        max_sl_points=max_sl_points,
    ):
        setup.first_confirm = None
        return None
    return EntrySignal(
        side=setup.side,
        entry_ts=bar["timestamp"],
        entry_price=entry,
        stop_loss=stop,
        target=target,
        swing_price=setup.swing.price,
        sweep_extreme=setup.sweep_extreme,
        grab_ts=setup.grab_ts,
        first_high=float(first["high"]),
        first_low=float(first["low"]),
    )
