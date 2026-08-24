"""15m decides buy/sell. Entry and SL are on 5m. Session opens only."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import BAR_SECONDS, MAX_STOP_POINTS
from src.risk import round_to_tick
from src.session import is_london_open, is_us_open, parse_bar_time

STRATEGY_ID = "HTF15_LTF5"
STOP_TICK = 0.05
HTF_SECONDS = 15 * 60


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
    pair_5m = _consecutive_pair(candles, BAR_SECONDS)
    if pair_5m is None:
        return None
    first_5m, second_5m = pair_5m
    first_time = parse_bar_time(first_5m["timestamp"])
    second_time = parse_bar_time(second_5m["timestamp"])
    session = _session_name(first_time, second_time)
    if session is None:
        return None
    bias = _htf_bias(candles, session)
    if bias is None:
        return None
    return _ltf_entry(first_5m, second_5m, after_loss, session, bias)


def _session_name(first_time: datetime, second_time: datetime) -> str | None:
    if is_london_open(first_time) and is_london_open(second_time):
        return "LONDON"
    if is_us_open(first_time) and is_us_open(second_time):
        return "US"
    return None


def _htf_bias(candles_5m: list[dict], session: str) -> str | None:
    htf = _closed_15m(candles_5m)
    pair = _consecutive_pair(htf, HTF_SECONDS)
    if pair is None:
        return None
    first, second = pair
    if _session_name(parse_bar_time(first["timestamp"]), parse_bar_time(second["timestamp"])) != session:
        return None
    if _is_red(first) and _is_red(second):
        return "short"
    if _is_green(first) and _is_green(second):
        return "long"
    return None


def _ltf_entry(
    first: dict, second: dict, after_loss: bool, session: str, bias: str
) -> Signal | None:
    if bias == "short":
        if not (_is_red(first) and _is_red(second)):
            return None
        stop = _stop_from_first_high(first, after_loss)
        reason = f"{session} 15m sell + 5m 2 red"
        if after_loss:
            reason += " (retry SL above first 5m high)"
        return _build("short", reason, second, stop, session)
    if not (_is_green(first) and _is_green(second)):
        return None
    stop = _stop_from_first_low(first, after_loss)
    reason = f"{session} 15m buy + 5m 2 green"
    if after_loss:
        reason += " (retry SL below first 5m low)"
    return _build("long", reason, second, stop, session)


def _closed_15m(candles_5m: list[dict]) -> list[dict]:
    if not candles_5m:
        return []
    buckets: dict[str, list[dict]] = {}
    order: list[str] = []
    for candle in candles_5m:
        start = _htf_floor(parse_bar_time(candle["timestamp"]))
        key = start.isoformat()
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(candle)
    last_end = parse_bar_time(candles_5m[-1]["timestamp"]).timestamp() + BAR_SECONDS
    rows: list[dict] = []
    for key in order:
        start = parse_bar_time(key)
        if start.timestamp() + HTF_SECONDS > last_end + 0.01:
            continue
        group = buckets[key]
        rows.append(
            {
                "timestamp": start.replace(tzinfo=timezone.utc).isoformat()
                if start.tzinfo is None
                else start.isoformat(),
                "open": float(group[0]["open"]),
                "high": max(float(bar["high"]) for bar in group),
                "low": min(float(bar["low"]) for bar in group),
                "close": float(group[-1]["close"]),
                "volume": sum(float(bar.get("volume") or 0) for bar in group),
            }
        )
    return rows


def _htf_floor(moment: datetime) -> datetime:
    minute = (moment.minute // 15) * 15
    return moment.replace(minute=minute, second=0, microsecond=0)


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
    if abs(entry - stop) > MAX_STOP_POINTS:
        return None
    return Signal(side, reason, entry_candle, stop, session)


def _consecutive_pair(candles: list[dict], bar_seconds: int) -> tuple[dict, dict] | None:
    if len(candles) < 2:
        return None
    first, second = candles[-2], candles[-1]
    gap = parse_bar_time(second["timestamp"]) - parse_bar_time(first["timestamp"])
    if abs(gap.total_seconds() - bar_seconds) > 1:
        return None
    return first, second


def _is_red(candle: dict) -> bool:
    return float(candle["close"]) < float(candle["open"])


def _is_green(candle: dict) -> bool:
    return float(candle["close"]) > float(candle["open"])
