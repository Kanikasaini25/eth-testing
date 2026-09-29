"""Structure guards for LQDTY liquidity-line entries.

Fresh-extreme retest: once price is beyond a liquidity line, a sweep signal is
only valid right after price breaks the day's latest lower low (long) / higher
high (short) and retests it; candles in the middle of the range are ignored.

When price keeps printing higher highs after breaking the previous-day high,
a plain two-red-candle short fades a trending market. In that case the short
is allowed only after a change of character: a candle closes below the last
higher low, price retests that broken level, and only then the usual
two-red-candle formula may fire. Longs below the previous-day low mirror this
(lower lows -> close above the last lower high -> retest -> two green candles).
"""

from __future__ import annotations

from dataclasses import dataclass

from src.timezone import delta_candle_day


@dataclass(frozen=True)
class StructureParams:
    enabled: bool = False
    pivot_bars: int = 10
    min_trend_swings: int = 3
    retest_tolerance_points: float = 1.0
    retest_window_bars: int = 5
    lookback_bars: int = 240
    require_fresh_extreme: bool = False
    fresh_window_bars: int = 3
    fresh_tolerance_points: float = 1.0


@dataclass(frozen=True)
class StructureCheck:
    """Outcome of the structure guard for one bar.

    trending: price is (or was, without a fresh retest) trending through the line.
    ready: change of character + retest happened recently; a sweep signal may form
        on this bar even if it does not trade beyond the liquidity line.
    """

    trending: bool = False
    ready: bool = False
    broken_level: float = 0.0
    break_index: int = -1
    reason: str = ""

    @property
    def blocks_entry(self) -> bool:
        return self.trending and not self.ready


def structure_params_from_dict(params: dict) -> StructureParams:
    return StructureParams(
        enabled=bool(params.get("use_trend_structure_filter", False)),
        pivot_bars=max(1, int(params.get("structure_pivot_bars", 10))),
        min_trend_swings=max(2, int(params.get("structure_min_trend_swings", 3))),
        retest_tolerance_points=float(params.get("structure_retest_tolerance_points", 1.0)),
        retest_window_bars=max(0, int(params.get("structure_retest_window_bars", 5))),
        lookback_bars=max(10, int(params.get("structure_lookback_bars", 240))),
        require_fresh_extreme=bool(params.get("require_fresh_extreme_retest", True)),
        fresh_window_bars=max(0, int(params.get("fresh_extreme_window_bars", 3))),
        fresh_tolerance_points=float(params.get("fresh_extreme_tolerance_points", 1.0)),
    )


def _same_day(timestamp: str, day: str) -> bool:
    if timestamp.endswith("+00:00"):
        return timestamp[:10] == day
    return delta_candle_day(timestamp) == day


def _window_start(rows: list[dict], index: int, lookback: int) -> int:
    day = delta_candle_day(rows[index]["timestamp"])
    start = index
    floor = max(0, index - lookback + 1)
    while start > floor and _same_day(rows[start - 1]["timestamp"], day):
        start -= 1
    return start


def retests_fresh_extreme(
    side: str,
    rows: list[dict],
    index: int,
    level: float,
    params: StructureParams,
) -> bool:
    """True when this bar sits on a fresh day extreme beyond the line.

    LONG: within `fresh_window_bars` a candle broke the day's lowest low (below the
    previous-day low) and this bar's low retests that new low within tolerance.
    SHORT mirrors it with the day's highest high above the previous-day high.
    Green/red candles in the middle of a range, away from the latest extreme, fail.
    """
    if index < 0 or index >= len(rows):
        return False
    key, sign = ("high", 1.0) if side == "short" else ("low", -1.0)
    extreme = float("-inf")
    extreme_at = -1
    for cursor in range(_window_start(rows, index, len(rows)), index + 1):
        value = float(rows[cursor][key]) * sign
        if value > extreme:
            extreme = value
            extreme_at = cursor
    if extreme <= level * sign:
        return False
    current = float(rows[index][key]) * sign
    return (
        index - extreme_at <= params.fresh_window_bars
        and extreme - current <= params.fresh_tolerance_points
    )


def _oriented_prices(
    rows: list[dict], start: int, index: int, side: str
) -> tuple[list[float], list[float], list[float]]:
    """Return (highs, lows, closes) so a LONG is analysed as a mirrored SHORT."""
    window = rows[start : index + 1]
    if side == "short":
        return (
            [float(row["high"]) for row in window],
            [float(row["low"]) for row in window],
            [float(row["close"]) for row in window],
        )
    return (
        [-float(row["low"]) for row in window],
        [-float(row["high"]) for row in window],
        [-float(row["close"]) for row in window],
    )


def _higher_high_swings(highs: list[float], level: float, first_break: int, k: int) -> list[int]:
    """Confirmed swing highs above the line that each exceed the previous one."""
    swings: list[int] = []
    last = len(highs) - 1
    for i in range(max(first_break, k), last - k + 1):
        high = highs[i]
        if high <= level:
            continue
        if high <= max(highs[i - k : i]) or high < max(highs[i + 1 : i + k + 1]):
            continue
        if not swings or high > highs[swings[-1]]:
            swings.append(i)
    return swings


def _describe(side: str, stage: str, price: float = 0.0) -> str:
    trend, swing, direction = (
        ("higher highs above previous-day high", "higher low", "below")
        if side == "short"
        else ("lower lows below previous-day low", "lower high", "above")
    )
    if stage == "trending":
        return f"trend still making {trend}"
    if stage == "await_break":
        return f"{trend}; waiting for a close {direction} {swing} {price:.2f}"
    return f"{swing} {price:.2f} broken; waiting for retest"


def evaluate_structure(
    side: str,
    rows: list[dict],
    index: int,
    level: float,
    params: StructureParams,
) -> StructureCheck:
    """Decide whether a sweep signal at `index` must wait for CHoCH + retest.

    Uses only bars up to `index` of the same UTC day, so it is safe for both the
    backtest loop and the live runner.
    """
    if not params.enabled or index < 0 or index >= len(rows):
        return StructureCheck()
    sign = 1.0 if side == "short" else -1.0
    start = _window_start(rows, index, params.lookback_bars)
    highs, lows, closes = _oriented_prices(rows, start, index, side)
    line = level * sign
    first_break = next((i for i, high in enumerate(highs) if high > line), None)
    if first_break is None:
        return StructureCheck()

    swings = _higher_high_swings(highs, line, first_break, params.pivot_bars)
    if not swings:
        return StructureCheck()
    top = swings[-1]
    printing_new_high = max(highs[top + 1 :], default=float("-inf")) > highs[top]
    if len(swings) + int(printing_new_high) < params.min_trend_swings:
        return StructureCheck()
    if printing_new_high:
        return StructureCheck(trending=True, reason=_describe(side, "trending"))

    previous = swings[-2]
    pullback = min(range(previous + 1, top), key=lows.__getitem__)
    higher_low = lows[pullback]
    real_level = higher_low * sign
    break_at = next(
        (j for j in range(top + 1, len(closes)) if closes[j] < higher_low), None
    )
    if break_at is None:
        return StructureCheck(
            trending=True, reason=_describe(side, "await_break", real_level)
        )

    retest_floor = higher_low - params.retest_tolerance_points
    retest_at = next(
        (j for j in range(len(highs) - 1, break_at, -1) if highs[j] >= retest_floor),
        None,
    )
    if retest_at is None:
        return StructureCheck(
            trending=True,
            broken_level=real_level,
            break_index=start + break_at,
            reason=_describe(side, "await_retest", real_level),
        )
    if len(highs) - 1 - retest_at > params.retest_window_bars:
        return StructureCheck()
    return StructureCheck(
        trending=True,
        ready=True,
        broken_level=real_level,
        break_index=start + break_at,
    )
