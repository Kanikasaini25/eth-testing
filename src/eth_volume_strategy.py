"""ETH India-session volume-bias + pullback entry rules."""

from __future__ import annotations

from dataclasses import dataclass

from src.delta_data import RESOLUTION_SECONDS
from src.timezone import india_calendar_day, india_now, parse_utc_timestamp, to_delta_time

CLOSE_TARGET_PCT = 5.0  # full close at +5%
DEFAULT_ENTRY_HOUR_IST = 19  # 7:00 PM IST after the India trading day
DEFAULT_POSITION_LOTS = 100
DEFAULT_PULLBACK_RESOLUTION = "15m"
DEFAULT_ENTRY_RESOLUTION = "1m"


@dataclass(frozen=True)
class VolumeBias:
    buy_volume: float
    sell_volume: float
    side: str

    @property
    def label(self) -> str:
        if self.side == "long":
            return "BUY"
        if self.side == "short":
            return "SELL"
        return "NONE"


@dataclass(frozen=True)
class Pullback:
    timestamp: str
    high: float
    low: float
    close: float


def candle_side(row: dict) -> str:
    """Return buy/sell/flat from candle body direction."""
    open_price = float(row["open"])
    close_price = float(row["close"])
    if close_price > open_price:
        return "buy"
    if close_price < open_price:
        return "sell"
    return "flat"


def accumulate_side_volume(rows: list[dict]) -> tuple[float, float]:
    """Sum volume on bullish vs bearish candles."""
    buy_volume = 0.0
    sell_volume = 0.0
    for row in rows:
        volume = float(row.get("volume") or 0)
        side = candle_side(row)
        if side == "buy":
            buy_volume += volume
        elif side == "sell":
            sell_volume += volume
    return buy_volume, sell_volume


def bias_from_volume(buy_volume: float, sell_volume: float) -> str:
    """Market power: more buy-volume → long, more sell-volume → short."""
    if buy_volume > sell_volume:
        return "long"
    if sell_volume > buy_volume:
        return "short"
    return ""


def measure_volume_bias(rows: list[dict]) -> VolumeBias:
    buy_volume, sell_volume = accumulate_side_volume(rows)
    return VolumeBias(
        buy_volume=buy_volume,
        sell_volume=sell_volume,
        side=bias_from_volume(buy_volume, sell_volume),
    )


def is_bias_window(timestamp: str, entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST) -> bool:
    """True for candles before the 7:00 PM IST entry hour."""
    local = to_delta_time(timestamp)
    return (local.hour, local.minute) < (entry_hour_ist, 0)


def is_entry_window(timestamp: str, entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST) -> bool:
    """True from 7:00 PM IST until India midnight."""
    local = to_delta_time(timestamp)
    return (local.hour, local.minute) >= (entry_hour_ist, 0)


def now_in_entry_window(entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST) -> bool:
    local = india_now()
    return (local.hour, local.minute) >= (entry_hour_ist, 0)


def bars_on_india_day(rows: list[dict], day: str) -> list[dict]:
    return [row for row in rows if india_calendar_day(row["timestamp"]) == day]


def closed_bars_on_day(
    rows: list[dict],
    day: str,
    now_ts: float,
    bar_seconds: int,
) -> list[dict]:
    """India-day bars whose candle period has fully closed."""
    closed: list[dict] = []
    for row in bars_on_india_day(rows, day):
        bar_end = parse_utc_timestamp(row["timestamp"]).timestamp() + bar_seconds
        if bar_end <= now_ts:
            closed.append(row)
    return closed


def order_side(side: str) -> str:
    return "buy" if side == "long" else "sell"


def exit_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def split_session_bars(
    rows: list[dict],
    day: str,
    entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST,
) -> tuple[list[dict], list[dict]]:
    """Split today's India bars into volume-observation vs pullback-entry windows."""
    today_bars = bars_on_india_day(rows, day)
    bias_bars = [row for row in today_bars if is_bias_window(row["timestamp"], entry_hour_ist)]
    entry_bars = [row for row in today_bars if is_entry_window(row["timestamp"], entry_hour_ist)]
    return bias_bars, entry_bars


def is_pullback_candle(row: dict, bias: str) -> bool:
    """A pullback is one closed candle against the day's market power."""
    side = candle_side(row)
    if bias == "long":
        return side == "sell"
    if bias == "short":
        return side == "buy"
    return False


def first_pullback(
    entry_bars: list[dict],
    bias: str,
    after_timestamp: str = "",
) -> Pullback | None:
    """Return the next post-7pm 15m pullback after a failed setup, if any."""
    for row in entry_bars:
        timestamp = str(row["timestamp"])
        if after_timestamp and timestamp <= after_timestamp:
            continue
        if not is_pullback_candle(row, bias):
            continue
        return Pullback(
            timestamp=timestamp,
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
    return None


def is_confirmation_candle(row: dict, bias: str) -> bool:
    """1m confirmation is a closed candle in the same direction as day market power."""
    side = candle_side(row)
    if bias == "long":
        return side == "buy"
    if bias == "short":
        return side == "sell"
    return False


def pullback_end_ts(pullback: Pullback, pullback_resolution: str = DEFAULT_PULLBACK_RESOLUTION) -> float:
    bar_seconds = RESOLUTION_SECONDS.get(pullback_resolution, 900)
    return parse_utc_timestamp(pullback.timestamp).timestamp() + bar_seconds


def first_confirmation(
    entry_bars: list[dict],
    pullback: Pullback,
    bias: str,
    pullback_resolution: str = DEFAULT_PULLBACK_RESOLUTION,
) -> dict | None:
    """First 1m candle after the 15m pullback closes that confirms the day's side."""
    cutoff = pullback_end_ts(pullback, pullback_resolution)
    for row in entry_bars:
        if parse_utc_timestamp(row["timestamp"]).timestamp() < cutoff:
            continue
        if is_confirmation_candle(row, bias):
            return row
    return None


def pullback_and_confirmation(
    pullback_rows: list[dict],
    entry_rows: list[dict],
    day: str,
    bias: str,
    entry_hour_ist: int = DEFAULT_ENTRY_HOUR_IST,
    pullback_resolution: str = DEFAULT_PULLBACK_RESOLUTION,
    after_timestamp: str = "",
) -> tuple[Pullback | None, dict | None]:
    """Next 15m pullback after 7pm IST (skipping failed ones), then 1m confirmation."""
    _bias_bars, entry_15m = split_session_bars(pullback_rows, day, entry_hour_ist)
    pullback = first_pullback(entry_15m, bias, after_timestamp)
    if pullback is None:
        return None, None
    return pullback, first_confirmation(entry_rows, pullback, bias, pullback_resolution)


def pullback_stop_loss(pullback: Pullback, side: str) -> float:
    """Stop marks the pullback wick: low for longs, high for shorts."""
    if side == "long":
        return pullback.low
    return pullback.high


def price_at_profit_pct(side: str, entry_price: float, pct: float) -> float:
    """Price that is `pct` percent in favor of `side` from entry."""
    fraction = pct / 100.0
    if side == "long":
        return entry_price * (1.0 + fraction)
    return entry_price * (1.0 - fraction)


def target_price(side: str, entry_price: float, pct: float = CLOSE_TARGET_PCT) -> float:
    """Full-position close price at +5% (or `pct`)."""
    return price_at_profit_pct(side, entry_price, pct)


def favorable_move_pct(side: str, entry_price: float, price: float) -> float:
    """How far `price` has moved in favor of the trade, as a percent of entry."""
    if entry_price <= 0:
        return 0.0
    if side == "long":
        return ((price - entry_price) / entry_price) * 100.0
    return ((entry_price - price) / entry_price) * 100.0


def locked_trail_pct(move_pct: float) -> float | None:
    """Map favorable move to a new SL lock. +1% keeps the initial wick SL."""
    if move_pct >= 4.0:
        return 3.0
    if move_pct >= 3.0:
        return 2.0
    if move_pct >= 2.0:
        return 1.0
    return None


def trail_stop_price(side: str, entry_price: float, initial_stop: float, move_pct: float) -> float:
    locked = locked_trail_pct(move_pct)
    if locked is None:
        return initial_stop
    return price_at_profit_pct(side, entry_price, locked)


def is_tighter_stop(side: str, new_stop: float, current_stop: float) -> bool:
    if side == "long":
        return new_stop > current_stop
    return new_stop < current_stop


def stop_is_valid(side: str, entry_price: float, stop_loss: float) -> bool:
    if side == "long":
        return stop_loss < entry_price
    return stop_loss > entry_price


def decide_open_trade(
    side: str,
    entry_price: float,
    initial_stop: float,
    current_stop: float,
    target: float,
    mark_price: float,
) -> tuple[str, float]:
    """Return (take_profit|stop_loss|trail|hold, working stop)."""
    target_hit = mark_price >= target if side == "long" else mark_price <= target
    stop_hit = mark_price <= current_stop if side == "long" else mark_price >= current_stop
    if target_hit:
        return "take_profit", current_stop
    if stop_hit:
        return "stop_loss", current_stop
    move_pct = favorable_move_pct(side, entry_price, mark_price)
    new_stop = trail_stop_price(side, entry_price, initial_stop, move_pct)
    if is_tighter_stop(side, new_stop, current_stop):
        return "trail", new_stop
    return "hold", current_stop


MAX_WINS_PER_DAY = 2
MAX_LOSSES_PER_DAY = 2


def signed_points(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return exit_price - entry_price
    return entry_price - exit_price


def day_limit_reached(wins: int, losses: int) -> bool:
    return wins >= MAX_WINS_PER_DAY or losses >= MAX_LOSSES_PER_DAY
