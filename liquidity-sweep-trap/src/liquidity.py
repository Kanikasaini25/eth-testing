from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Pivot:
    index: int
    price: float
    timestamp: str
    kind: str


@dataclass(frozen=True)
class LiquidityLevel:
    side: str
    price: float
    kind: str
    strength: int
    timestamp: str
    htf_index: int


def resample_ohlcv(rows: list[dict], minutes: int) -> list[dict]:
    """Aggregate lower-timeframe candles into higher-timeframe buckets."""
    if not rows:
        return []

    bucket_seconds = minutes * 60
    buckets: dict[int, dict] = {}

    for row in rows:
        ts = datetime.fromisoformat(row["timestamp"])
        bucket_start = int(ts.timestamp()) // bucket_seconds * bucket_seconds
        candle = buckets.get(bucket_start)
        if candle is None:
            buckets[bucket_start] = {
                "timestamp": datetime.fromtimestamp(bucket_start, tz=ts.tzinfo).isoformat(),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            }
            continue

        candle["high"] = max(candle["high"], float(row["high"]))
        candle["low"] = min(candle["low"], float(row["low"]))
        candle["close"] = float(row["close"])
        candle["volume"] += float(row["volume"])

    return [buckets[key] for key in sorted(buckets)]


def completed_htf_rows(
    htf_rows: list[dict],
    timestamp: str,
    tf_minutes: int,
) -> list[dict]:
    """HTF candles that have already closed before this timestamp."""
    current = datetime.fromisoformat(timestamp)
    duration = timedelta(minutes=tf_minutes)
    completed: list[dict] = []
    for row in htf_rows:
        start = datetime.fromisoformat(row["timestamp"])
        if start + duration <= current:
            completed.append(row)
            continue
        break
    return completed


def find_pivot_highs(rows: list[dict], left: int, right: int) -> list[Pivot]:
    pivots: list[Pivot] = []
    for index in range(left, len(rows) - right):
        high = float(rows[index]["high"])
        left_ok = all(high > float(rows[j]["high"]) for j in range(index - left, index))
        right_ok = all(high > float(rows[j]["high"]) for j in range(index + 1, index + right + 1))
        if left_ok and right_ok:
            pivots.append(
                Pivot(index=index, price=high, timestamp=rows[index]["timestamp"], kind="high")
            )
    return pivots


def find_pivot_lows(rows: list[dict], left: int, right: int) -> list[Pivot]:
    pivots: list[Pivot] = []
    for index in range(left, len(rows) - right):
        low = float(rows[index]["low"])
        left_ok = all(low < float(rows[j]["low"]) for j in range(index - left, index))
        right_ok = all(low < float(rows[j]["low"]) for j in range(index + 1, index + right + 1))
        if left_ok and right_ok:
            pivots.append(
                Pivot(index=index, price=low, timestamp=rows[index]["timestamp"], kind="low")
            )
    return pivots


def _cluster_pivots(pivots: list[Pivot], tolerance_pct: float, side: str) -> list[LiquidityLevel]:
    if not pivots:
        return []

    remaining = sorted(pivots, key=lambda item: item.price)
    used: set[int] = set()
    levels: list[LiquidityLevel] = []

    for index, pivot in enumerate(remaining):
        if index in used:
            continue
        group = [pivot]
        used.add(index)
        for other_index in range(index + 1, len(remaining)):
            if other_index in used:
                continue
            other = remaining[other_index]
            distance_pct = abs(other.price - pivot.price) / pivot.price * 100
            if distance_pct <= tolerance_pct:
                group.append(other)
                used.add(other_index)

        latest = max(group, key=lambda item: item.index)
        equal = len(group) >= 2
        if side == "buy_side":
            price = max(item.price for item in group)
            kind = "equal_highs" if equal else "swing_high"
        else:
            price = min(item.price for item in group)
            kind = "equal_lows" if equal else "swing_low"

        levels.append(
            LiquidityLevel(
                side=side,
                price=price,
                kind=kind,
                strength=len(group),
                timestamp=latest.timestamp,
                htf_index=latest.index,
            )
        )
    return levels


def _previous_day_levels(htf_rows: list[dict], timestamp: str, max_days: int = 3) -> list[LiquidityLevel]:
    """Previous completed daily highs/lows — typical stop clusters, not every HTF candle."""
    current_day = datetime.fromisoformat(timestamp).date()
    by_day: dict = {}
    for index, row in enumerate(htf_rows):
        day = datetime.fromisoformat(row["timestamp"]).date()
        if day >= current_day:
            break
        bucket = by_day.get(day)
        if bucket is None:
            by_day[day] = {
                "high": float(row["high"]),
                "low": float(row["low"]),
                "timestamp": row["timestamp"],
                "index": index,
            }
            continue
        bucket["high"] = max(bucket["high"], float(row["high"]))
        bucket["low"] = min(bucket["low"], float(row["low"]))
        bucket["index"] = index

    levels: list[LiquidityLevel] = []
    for day in sorted(by_day, reverse=True)[:max_days]:
        bucket = by_day[day]
        levels.append(
            LiquidityLevel(
                side="buy_side",
                price=bucket["high"],
                kind="previous_high",
                strength=1,
                timestamp=bucket["timestamp"],
                htf_index=bucket["index"],
            )
        )
        levels.append(
            LiquidityLevel(
                side="sell_side",
                price=bucket["low"],
                kind="previous_low",
                strength=1,
                timestamp=bucket["timestamp"],
                htf_index=bucket["index"],
            )
        )
    return levels


def _merge_near_levels(levels: list[LiquidityLevel], tolerance_pct: float) -> list[LiquidityLevel]:
    if not levels:
        return []

    kind_rank = {
        "equal_highs": 3,
        "equal_lows": 3,
        "swing_high": 2,
        "swing_low": 2,
        "previous_high": 1,
        "previous_low": 1,
    }
    merged: list[LiquidityLevel] = []
    for level in sorted(levels, key=lambda item: (item.side, item.price)):
        if not merged:
            merged.append(level)
            continue
        previous = merged[-1]
        same_side = previous.side == level.side
        close_enough = abs(level.price - previous.price) / previous.price * 100 <= tolerance_pct
        if not (same_side and close_enough):
            merged.append(level)
            continue

        previous_score = (kind_rank.get(previous.kind, 0), previous.strength, previous.htf_index)
        level_score = (kind_rank.get(level.kind, 0), level.strength, level.htf_index)
        if level_score >= previous_score:
            merged[-1] = level
    return merged


def liquidity_at(
    htf_rows: list[dict],
    timestamp: str,
    *,
    tf_minutes: int,
    pivot_left: int,
    pivot_right: int,
    lookback: int,
    equal_tolerance_pct: float,
) -> list[LiquidityLevel]:
    completed = completed_htf_rows(htf_rows, timestamp, tf_minutes)
    if len(completed) < pivot_left + pivot_right + 3:
        return []

    min_index = max(0, len(completed) - lookback)
    highs = [item for item in find_pivot_highs(completed, pivot_left, pivot_right) if item.index >= min_index]
    lows = [item for item in find_pivot_lows(completed, pivot_left, pivot_right) if item.index >= min_index]

    levels = _cluster_pivots(highs, equal_tolerance_pct, "buy_side")
    levels.extend(_cluster_pivots(lows, equal_tolerance_pct, "sell_side"))
    levels.extend(_previous_day_levels(completed, timestamp))
    return _merge_near_levels(levels, equal_tolerance_pct)


def nearest_liquidity(
    levels: list[LiquidityLevel],
    price: float,
) -> tuple[LiquidityLevel | None, LiquidityLevel | None]:
    """Nearest buy-side liquidity above price, nearest sell-side liquidity below price."""
    above = [level for level in levels if level.side == "buy_side" and level.price > price]
    below = [level for level in levels if level.side == "sell_side" and level.price < price]
    nearest_above = min(above, key=lambda level: level.price) if above else None
    nearest_below = max(below, key=lambda level: level.price) if below else None
    return nearest_above, nearest_below


def next_target_liquidity(
    levels: list[LiquidityLevel],
    *,
    direction: str,
    entry_price: float,
    swept_price: float,
) -> LiquidityLevel | None:
    if direction == "long":
        candidates = [
            level
            for level in levels
            if level.side == "buy_side" and level.price > entry_price and level.price != swept_price
        ]
        return min(candidates, key=lambda level: level.price) if candidates else None

    candidates = [
        level
        for level in levels
        if level.side == "sell_side" and level.price < entry_price and level.price != swept_price
    ]
    return max(candidates, key=lambda level: level.price) if candidates else None
