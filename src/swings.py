from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

M15_SECONDS = 900


def epoch_of(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()


def last_closed_bar_open(now_epoch: float, bar_seconds: int) -> float:
    current_open = now_epoch - (now_epoch % bar_seconds)
    return current_open - bar_seconds


def last_closed_m15_open(now_epoch: float) -> float:
    return last_closed_bar_open(now_epoch, M15_SECONDS)


@dataclass(frozen=True)
class SwingPoint:
    kind: str
    price: float
    m15_index: int
    timestamp: str
    confirm_index: int

    @property
    def swing_id(self) -> str:
        return f"{self.kind}:{self.m15_index}:{self.timestamp}"


def _is_strict_pivot(values: list[float], index: int, left: int, right: int, want_max: bool) -> bool:
    pivot = values[index]
    start = index - left
    end = index + right + 1
    for other in range(start, end):
        if other == index:
            continue
        if want_max and values[other] >= pivot:
            return False
        if not want_max and values[other] <= pivot:
            return False
    return True


def detect_swings(m15_rows: list[dict], left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Fractal swings. A pivot at i is only known after bar i+right has closed."""
    if left < 1 or right < 1 or len(m15_rows) < left + right + 1:
        return []

    highs = [float(row["high"]) for row in m15_rows]
    lows = [float(row["low"]) for row in m15_rows]
    last_index = len(m15_rows) - right - 1
    swings: list[SwingPoint] = []

    for index in range(left, last_index + 1):
        timestamp = m15_rows[index]["timestamp"]
        confirm_index = index + right
        if _is_strict_pivot(highs, index, left, right, want_max=True):
            swings.append(
                SwingPoint("high", highs[index], index, timestamp, confirm_index)
            )
        if _is_strict_pivot(lows, index, left, right, want_max=False):
            swings.append(
                SwingPoint("low", lows[index], index, timestamp, confirm_index)
            )
    return swings


def usable_swings(
    swings: list[SwingPoint],
    last_closed_index: int,
    lookback: int,
    swept_ids: set[str],
) -> list[SwingPoint]:
    oldest = last_closed_index - lookback
    result: list[SwingPoint] = []
    for swing in swings:
        if swing.swing_id in swept_ids:
            continue
        if swing.confirm_index > last_closed_index:
            continue
        if swing.m15_index < oldest:
            continue
        result.append(swing)
    return result


def latest_swing(swings: list[SwingPoint], kind: str) -> SwingPoint | None:
    matches = [swing for swing in swings if swing.kind == kind]
    if not matches:
        return None
    return max(matches, key=lambda swing: swing.m15_index)
