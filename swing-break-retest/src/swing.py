from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SwingLevel:
    index: int
    price: float
    timestamp: str
    kind: str


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


def find_pivot_highs(rows: list[dict], left: int, right: int) -> list[SwingLevel]:
    pivots: list[SwingLevel] = []
    for index in range(left, len(rows) - right):
        high = float(rows[index]["high"])
        left_ok = all(high > float(rows[j]["high"]) for j in range(index - left, index))
        right_ok = all(high > float(rows[j]["high"]) for j in range(index + 1, index + right + 1))
        if left_ok and right_ok:
            pivots.append(
                SwingLevel(
                    index=index,
                    price=high,
                    timestamp=rows[index]["timestamp"],
                    kind="high",
                )
            )
    return pivots


def find_pivot_lows(rows: list[dict], left: int, right: int) -> list[SwingLevel]:
    pivots: list[SwingLevel] = []
    for index in range(left, len(rows) - right):
        low = float(rows[index]["low"])
        left_ok = all(low < float(rows[j]["low"]) for j in range(index - left, index))
        right_ok = all(low < float(rows[j]["low"]) for j in range(index + 1, index + right + 1))
        if left_ok and right_ok:
            pivots.append(
                SwingLevel(
                    index=index,
                    price=low,
                    timestamp=rows[index]["timestamp"],
                    kind="low",
                )
            )
    return pivots


def latest_swings_before(
    rows: list[dict],
    upto_index: int,
    pivot_left: int,
    pivot_right: int,
) -> tuple[SwingLevel | None, SwingLevel | None]:
    """Return the most recent swing high and swing low confirmed before upto_index."""
    window = rows[:upto_index]
    if len(window) <= pivot_left + pivot_right:
        return None, None

    highs = [p for p in find_pivot_highs(window, pivot_left, pivot_right) if p.index < upto_index]
    lows = [p for p in find_pivot_lows(window, pivot_left, pivot_right) if p.index < upto_index]
    swing_high = highs[-1] if highs else None
    swing_low = lows[-1] if lows else None
    return swing_high, swing_low
