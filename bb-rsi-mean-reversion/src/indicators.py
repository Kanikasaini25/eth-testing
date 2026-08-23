"""SMA Bollinger Bands and Cutler's RSI. No EMA / Wilder smoothing is used."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IndicatorSnapshot:
    sma: float
    upper_band: float
    lower_band: float
    rsi: float
    stdev: float


def sma(values: list[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def population_stdev(values: list[float]) -> float:
    """TradingView-style population stdev (divide by n, not n-1)."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((item - mean) ** 2 for item in values) / len(values)
    return variance ** 0.5


def bollinger_bands(
    closes: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[float, float, float, float] | None:
    """Return (sma, upper, lower, stdev) from an SMA — never an EMA."""
    middle = sma(closes, period)
    if middle is None:
        return None
    window = closes[-period:]
    stdev = population_stdev(window)
    width = num_std * stdev
    return middle, middle + width, middle - width, stdev


def rsi_cutler(closes: list[float], period: int = 14) -> float | None:
    """
    Cutler's RSI: SMA of gains and SMA of losses.

    Wilder's RSI uses EMA-like smoothing. This strategy forbids EMA, so we use SMA.
    """
    if period <= 0 or len(closes) < period + 1:
        return None

    window = closes[-(period + 1) :]
    gains = 0.0
    losses = 0.0
    for index in range(1, len(window)):
        change = window[index] - window[index - 1]
        if change > 0:
            gains += change
        else:
            losses += abs(change)

    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    if avg_gain == 0:
        return 0.0
    relative_strength = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + relative_strength))


def snapshot(
    closes: list[float],
    *,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
) -> IndicatorSnapshot | None:
    bands = bollinger_bands(closes, bb_period, bb_std)
    rsi = rsi_cutler(closes, rsi_period)
    if bands is None or rsi is None:
        return None
    middle, upper, lower, stdev = bands
    return IndicatorSnapshot(
        sma=middle,
        upper_band=upper,
        lower_band=lower,
        rsi=rsi,
        stdev=stdev,
    )


def indicator_series(
    closes: list[float],
    *,
    bb_period: int = 20,
    bb_std: float = 2.0,
    rsi_period: int = 14,
) -> dict[str, list[float | None]]:
    sma_vals: list[float | None] = []
    upper_vals: list[float | None] = []
    lower_vals: list[float | None] = []
    rsi_vals: list[float | None] = []
    for index in range(len(closes)):
        snap = snapshot(closes[: index + 1], bb_period=bb_period, bb_std=bb_std, rsi_period=rsi_period)
        sma_vals.append(snap.sma if snap else None)
        upper_vals.append(snap.upper_band if snap else None)
        lower_vals.append(snap.lower_band if snap else None)
        rsi_vals.append(snap.rsi if snap else None)
    return {"sma": sma_vals, "upper": upper_vals, "lower": lower_vals, "rsi": rsi_vals}
