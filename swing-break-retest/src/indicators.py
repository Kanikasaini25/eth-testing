from __future__ import annotations


def compute_rsi(closes: list[float], period: int = 14) -> list[float | None]:
    """Wilder RSI. Returns None until enough candles exist."""
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result

    avg_gain = 0.0
    avg_loss = 0.0
    for index in range(1, period + 1):
        change = closes[index] - closes[index - 1]
        avg_gain += max(change, 0.0)
        avg_loss += max(-change, 0.0)
    avg_gain /= period
    avg_loss /= period

    for index in range(period, len(closes)):
        if index > period:
            change = closes[index] - closes[index - 1]
            avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
            avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period

        if avg_loss == 0:
            result[index] = 100.0
        else:
            rs = avg_gain / avg_loss
            result[index] = 100.0 - (100.0 / (1.0 + rs))

    return result
