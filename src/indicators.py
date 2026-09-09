from __future__ import annotations

from datetime import datetime, timezone


def ema(values: list[float], period: int) -> list[float | None]:
    if period < 1 or not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out: list[float | None] = [None] * len(values)
    seed = values[:period]
    if len(seed) < period:
        return out
    current = sum(seed) / period
    out[period - 1] = current
    for index in range(period, len(values)):
        current = values[index] * alpha + current * (1.0 - alpha)
        out[index] = current
    return out


def rsi(closes: list[float], period: int = 14) -> list[float | None]:
    if period < 1 or len(closes) <= period:
        return [None] * len(closes)
    out: list[float | None] = [None] * len(closes)
    gains = 0.0
    losses = 0.0
    for index in range(1, period + 1):
        move = closes[index] - closes[index - 1]
        if move >= 0:
            gains += move
        else:
            losses -= move
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for index in range(period + 1, len(closes)):
        move = closes[index] - closes[index - 1]
        gain = max(move, 0.0)
        loss = max(-move, 0.0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        if avg_loss == 0:
            out[index] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[index] = 100.0 - (100.0 / (1.0 + rs))
    return out


def true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return max(high - low, 0.0)
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(rows: list[dict], period: int = 14) -> list[float | None]:
    """Wilder ATR from OHLCV rows."""
    out: list[float | None] = [None] * len(rows)
    if period < 1 or len(rows) < period + 1:
        return out
    trs: list[float] = []
    prev_close: float | None = None
    for row in rows:
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        trs.append(true_range(high, low, prev_close))
        prev_close = close
    first = sum(trs[1 : period + 1]) / period
    out[period] = first
    current = first
    for index in range(period + 1, len(rows)):
        current = (current * (period - 1) + trs[index]) / period
        out[index] = current
    return out


def adx(rows: list[dict], period: int = 14) -> list[float | None]:
    """Wilder ADX. Returns None until enough bars exist."""
    n = len(rows)
    out: list[float | None] = [None] * n
    if period < 1 or n < period * 2:
        return out

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n
    for i in range(1, n):
        up = float(rows[i]["high"]) - float(rows[i - 1]["high"])
        down = float(rows[i - 1]["low"]) - float(rows[i]["low"])
        plus_dm[i] = up if up > down and up > 0 else 0.0
        minus_dm[i] = down if down > up and down > 0 else 0.0
        tr[i] = true_range(
            float(rows[i]["high"]),
            float(rows[i]["low"]),
            float(rows[i - 1]["close"]),
        )

    atr_s = sum(tr[1 : period + 1]) / period
    plus_s = sum(plus_dm[1 : period + 1]) / period
    minus_s = sum(minus_dm[1 : period + 1]) / period
    dx_values: list[float | None] = [None] * n

    def _dx(p: float, m: float, a: float) -> float:
        if a <= 0:
            return 0.0
        plus_di = 100.0 * p / a
        minus_di = 100.0 * m / a
        denom = plus_di + minus_di
        if denom <= 0:
            return 0.0
        return 100.0 * abs(plus_di - minus_di) / denom

    dx_values[period] = _dx(plus_s, minus_s, atr_s)
    for i in range(period + 1, n):
        atr_s = (atr_s * (period - 1) + tr[i]) / period
        plus_s = (plus_s * (period - 1) + plus_dm[i]) / period
        minus_s = (minus_s * (period - 1) + minus_dm[i]) / period
        dx_values[i] = _dx(plus_s, minus_s, atr_s)

    # First ADX is average of first `period` DX values starting at index `period`
    start = period
    end = period * 2
    if end >= n or any(dx_values[i] is None for i in range(start, end)):
        return out
    adx_val = sum(float(dx_values[i] or 0.0) for i in range(start, end)) / period
    out[end - 1] = adx_val
    for i in range(end, n):
        adx_val = (adx_val * (period - 1) + float(dx_values[i] or 0.0)) / period
        out[i] = adx_val
    return out


def bollinger(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    mid: list[float | None] = [None] * len(closes)
    upper: list[float | None] = [None] * len(closes)
    lower: list[float | None] = [None] * len(closes)
    if period < 2 or len(closes) < period:
        return mid, upper, lower
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = sum(window) / period
        var = sum((x - mean) ** 2 for x in window) / period
        std = var**0.5
        mid[i] = mean
        upper[i] = mean + num_std * std
        lower[i] = mean - num_std * std
    return mid, upper, lower


def donchian(
    rows: list[dict],
    period: int = 20,
) -> tuple[list[float | None], list[float | None]]:
    """N-bar high / low channel (Turtle-style)."""
    highs: list[float | None] = [None] * len(rows)
    lows: list[float | None] = [None] * len(rows)
    if period < 1 or len(rows) < period:
        return highs, lows
    for i in range(period - 1, len(rows)):
        # Prior N bars excluding current (breakout uses previous channel)
        window = rows[i - period + 1 : i + 1]
        highs[i] = max(float(r["high"]) for r in window)
        lows[i] = min(float(r["low"]) for r in window)
    return highs, lows


def donchian_prior(
    rows: list[dict],
    index: int,
    period: int,
) -> tuple[float | None, float | None]:
    """Highest high / lowest low of the prior `period` bars (excluding index)."""
    if index < period:
        return None, None
    window = rows[index - period : index]
    return (
        max(float(r["high"]) for r in window),
        min(float(r["low"]) for r in window),
    )


def average_volume(rows: list[dict], index: int, lookback: int) -> float:
    if index < lookback:
        return 0.0
    window = rows[index - lookback : index]
    if not window:
        return 0.0
    return sum(float(row.get("volume") or 0.0) for row in window) / len(window)


def utc_hour_from_ts(timestamp: str) -> int:
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).hour


def in_gold_session(
    timestamp: str,
    *,
    london_start: int = 7,
    london_end: int = 10,
    overlap_start: int = 12,
    overlap_end: int = 16,
) -> bool:
    """True during London open or London/NY overlap (UTC hours, inclusive start)."""
    hour = utc_hour_from_ts(timestamp)
    in_london = london_start <= hour < london_end
    in_overlap = overlap_start <= hour < overlap_end
    return in_london or in_overlap
