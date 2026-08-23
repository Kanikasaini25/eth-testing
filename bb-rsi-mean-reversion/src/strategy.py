"""1m close signals: SMA Bollinger + RSI, faded against the previous 1h run."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import (
    BB_PERIOD,
    BB_STD_DEV,
    HTF_BARS,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    RSI_PERIOD,
)
from src.indicators import IndicatorSnapshot, snapshot


@dataclass(frozen=True)
class HourTrend:
    direction: str
    open: float
    close: float


@dataclass(frozen=True)
class Signal:
    side: str
    reason: str
    indicators: IndicatorSnapshot
    candle: dict


def previous_hour_trend(candles: list[dict]) -> HourTrend | None:
    """OHLC of the 60 1m bars before the signal candle."""
    if len(candles) < HTF_BARS + 1:
        return None
    window = candles[-(HTF_BARS + 1) : -1]
    hour_open = float(window[0]["open"])
    hour_close = float(window[-1]["close"])
    if hour_close < hour_open:
        direction = "down"
    elif hour_close > hour_open:
        direction = "up"
    else:
        direction = "flat"
    return HourTrend(direction, hour_open, hour_close)


def evaluate_closed_candle(
    candles: list[dict], *, after_session_stop: bool = False
) -> Signal | None:
    if not candles:
        return None
    trend = previous_hour_trend(candles)
    if trend is None or trend.direction == "flat":
        return None
    closes = [float(row["close"]) for row in candles]
    indicators = snapshot(
        closes,
        bb_period=BB_PERIOD,
        bb_std=BB_STD_DEV,
        rsi_period=RSI_PERIOD,
    )
    if indicators is None:
        return None
    candle = candles[-1]
    if after_session_stop:
        return _fade_hour_signal(trend, indicators, candle)
    return _bb_rsi_signal(trend, indicators, candle)


def _bb_rsi_signal(
    trend: HourTrend, indicators: IndicatorSnapshot, candle: dict
) -> Signal | None:
    high = float(candle["high"])
    low = float(candle["low"])
    close = float(candle["close"])
    long_ok = _long_entry(low, close, indicators) and trend.direction == "down"
    short_ok = _short_entry(high, close, indicators) and trend.direction == "up"
    if long_ok and short_ok:
        return None
    if long_ok:
        return Signal("long", "fade 1h down run + lower BB + RSI < 30", indicators, candle)
    if short_ok:
        return Signal("short", "fade 1h up run + upper BB + RSI > 70", indicators, candle)
    return None


def _fade_hour_signal(
    trend: HourTrend, indicators: IndicatorSnapshot, candle: dict
) -> Signal | None:
    if trend.direction == "down":
        return Signal("long", "re-entry fade 1h down run", indicators, candle)
    if trend.direction == "up":
        return Signal("short", "re-entry fade 1h up run", indicators, candle)
    return None


def _long_entry(low: float, close: float, indicators: IndicatorSnapshot) -> bool:
    pierced = close <= indicators.lower_band or low <= indicators.lower_band
    return pierced and indicators.rsi < RSI_OVERSOLD


def _short_entry(high: float, close: float, indicators: IndicatorSnapshot) -> bool:
    pierced = close >= indicators.upper_band or high >= indicators.upper_band
    return pierced and indicators.rsi > RSI_OVERBOUGHT
