"""London = short only. US = long only. Two same-color 1m bars. No old close-vs-open side."""

from __future__ import annotations

from dataclasses import dataclass

from src.risk import round_to_tick
from src.session import is_london_open, is_us_open, parse_bar_time

STRATEGY_ID = "LONDON_SHORT_US_LONG"
STOP_TICK = 0.05


@dataclass(frozen=True)
class Signal:
    side: str
    reason: str
    candle: dict
    stop_price: float
    session: str


def evaluate_closed_candle(
    candles: list[dict],
    *,
    after_loss: bool = False,
    **_: object,
) -> Signal | None:
    pair = _consecutive_pair(candles)
    if pair is None:
        return None
    first, second = pair
    first_time = parse_bar_time(first["timestamp"])
    second_time = parse_bar_time(second["timestamp"])
    if is_london_open(first_time) and is_london_open(second_time):
        return _london_short(first, second, after_loss)
    if is_us_open(first_time) and is_us_open(second_time):
        return _us_long(first, second, after_loss)
    return None


def _london_short(first: dict, second: dict, after_loss: bool) -> Signal | None:
    if not (_is_red(first) and _is_red(second)):
        return None
    stop = _stop_from_first_high(first, after_loss)
    reason = "London 2 red 1m"
    if after_loss:
        reason += " (retry SL above first high)"
    return _build("short", reason, second, stop, "LONDON")


def _us_long(first: dict, second: dict, after_loss: bool) -> Signal | None:
    if not (_is_green(first) and _is_green(second)):
        return None
    stop = _stop_from_first_low(first, after_loss)
    reason = "US 2 green 1m"
    if after_loss:
        reason += " (retry SL below first low)"
    return _build("long", reason, second, stop, "US")


def _stop_from_first_high(first: dict, after_loss: bool) -> float:
    high = float(first["high"])
    if after_loss:
        return round_to_tick(high + STOP_TICK, STOP_TICK)
    return round_to_tick(high, STOP_TICK)


def _stop_from_first_low(first: dict, after_loss: bool) -> float:
    low = float(first["low"])
    if after_loss:
        return round_to_tick(low - STOP_TICK, STOP_TICK)
    return round_to_tick(low, STOP_TICK)


def _build(side: str, reason: str, entry_candle: dict, stop: float, session: str) -> Signal | None:
    entry = float(entry_candle["close"])
    if side == "long" and stop >= entry:
        return None
    if side == "short" and stop <= entry:
        return None
    return Signal(side, reason, entry_candle, stop, session)


def _consecutive_pair(candles: list[dict]) -> tuple[dict, dict] | None:
    if len(candles) < 2:
        return None
    first, second = candles[-2], candles[-1]
    gap = parse_bar_time(second["timestamp"]) - parse_bar_time(first["timestamp"])
    if abs(gap.total_seconds() - 60) > 1:
        return None
    return first, second


def _is_red(candle: dict) -> bool:
    return float(candle["close"]) < float(candle["open"])


def _is_green(candle: dict) -> bool:
    return float(candle["close"]) > float(candle["open"])
