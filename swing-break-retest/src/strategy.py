from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.indicators import compute_rsi
from src.swing import SwingLevel, latest_swings_before, resample_ohlcv


@dataclass
class BreakEvent:
    direction: str
    level: float
    break_timestamp: str
    break_index_30m: int
    swing: SwingLevel


@dataclass
class EntrySignal:
    direction: str
    entry_price: float
    entry_timestamp: str
    stop_loss: float
    take_profit: float
    broken_level: float
    retest_index: int
    rsi_at_entry: float | None = None


@dataclass
class StrategyConfig:
    setup_timeframe_minutes: int = 30
    entry_timeframe_minutes: int = 5
    pivot_left: int = 2
    pivot_right: int = 2
    retest_tolerance_pct: float = 0.15
    retest_window_candles: int = 36
    reward_risk_ratio: float = 2.0
    require_confirmation_candle: bool = True
    min_stop_loss_pct: float = 0.05
    max_stop_loss_pct: float = 1.5
    max_entry_distance_from_level_pct: float = 0.5
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_long_min: float = 50.0
    rsi_short_max: float = 50.0
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    starting_wallet_usd: float = 10_000.0


def _tolerance_price(level: float, tolerance_pct: float) -> float:
    return level * (tolerance_pct / 100)


def detect_breaks(
    candles_5m: list[dict],
    config: StrategyConfig,
) -> list[BreakEvent]:
    candles_30m = resample_ohlcv(candles_5m, config.setup_timeframe_minutes)
    events: list[BreakEvent] = []
    warmup = config.pivot_left + config.pivot_right + 2
    broken_swing_ids: set[str] = set()

    for index in range(warmup, len(candles_30m)):
        swing_high, swing_low = latest_swings_before(
            candles_30m,
            index,
            config.pivot_left,
            config.pivot_right,
        )
        if swing_high is None and swing_low is None:
            continue

        close = float(candles_30m[index]["close"])
        prev_close = float(candles_30m[index - 1]["close"]) if index > 0 else close
        timestamp = candles_30m[index]["timestamp"]

        high_break = (
            swing_high is not None
            and prev_close <= swing_high.price
            and close > swing_high.price
        )
        low_break = (
            swing_low is not None
            and prev_close >= swing_low.price
            and close < swing_low.price
        )

        if high_break and low_break:
            high_distance = abs(close - swing_high.price)
            low_distance = abs(close - swing_low.price)
            chosen = (
                BreakEvent(
                    direction="long",
                    level=swing_high.price,
                    break_timestamp=timestamp,
                    break_index_30m=index,
                    swing=swing_high,
                )
                if high_distance >= low_distance
                else BreakEvent(
                    direction="short",
                    level=swing_low.price,
                    break_timestamp=timestamp,
                    break_index_30m=index,
                    swing=swing_low,
                )
            )
        elif high_break:
            chosen = BreakEvent(
                direction="long",
                level=swing_high.price,
                break_timestamp=timestamp,
                break_index_30m=index,
                swing=swing_high,
            )
        elif low_break:
            chosen = BreakEvent(
                direction="short",
                level=swing_low.price,
                break_timestamp=timestamp,
                break_index_30m=index,
                swing=swing_low,
            )
        else:
            continue

        swing_id = f"{chosen.swing.kind}:{chosen.swing.timestamp}:{chosen.swing.price}"
        if swing_id in broken_swing_ids:
            continue
        broken_swing_ids.add(swing_id)
        events.append(chosen)

    return events


def find_retest_entry(
    candles_5m: list[dict],
    break_event: BreakEvent,
    config: StrategyConfig,
) -> EntrySignal | None:
    break_ts = datetime.fromisoformat(break_event.break_timestamp)
    tolerance = _tolerance_price(break_event.level, config.retest_tolerance_pct)

    start_index = next(
        (index for index, row in enumerate(candles_5m) if datetime.fromisoformat(row["timestamp"]) >= break_ts),
        None,
    )
    if start_index is None:
        return None

    end_index = min(len(candles_5m), start_index + config.retest_window_candles)
    closes = [float(row["close"]) for row in candles_5m]
    rsi_values = compute_rsi(closes, config.rsi_period) if config.use_rsi_filter else []

    for index in range(start_index + 1, end_index):
        row = candles_5m[index]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = row["timestamp"]

        if break_event.direction == "long":
            touched = low <= break_event.level + tolerance
            bullish = close > open_price
            confirmed = close > break_event.level
            if not touched:
                continue
            if config.require_confirmation_candle and not (bullish and confirmed):
                continue

            stop_loss = low
            risk = close - stop_loss
            if risk <= 0:
                continue
            if not _entry_valid("long", close, stop_loss, break_event.level, config):
                continue
            if not _rsi_valid("long", rsi_values, index, config):
                continue

            return EntrySignal(
                direction="long",
                entry_price=close,
                entry_timestamp=timestamp,
                stop_loss=stop_loss,
                take_profit=close + (risk * config.reward_risk_ratio),
                broken_level=break_event.level,
                retest_index=index,
                rsi_at_entry=rsi_values[index] if config.use_rsi_filter else None,
            )

        touched = high >= break_event.level - tolerance
        bearish = close < open_price
        confirmed = close < break_event.level
        if not touched:
            continue
        if config.require_confirmation_candle and not (bearish and confirmed):
            continue

        stop_loss = high
        risk = stop_loss - close
        if risk <= 0:
            continue
        if not _entry_valid("short", close, stop_loss, break_event.level, config):
            continue
        if not _rsi_valid("short", rsi_values, index, config):
            continue

        return EntrySignal(
            direction="short",
            entry_price=close,
            entry_timestamp=timestamp,
            stop_loss=stop_loss,
            take_profit=close - (risk * config.reward_risk_ratio),
            broken_level=break_event.level,
            retest_index=index,
            rsi_at_entry=rsi_values[index] if config.use_rsi_filter else None,
        )

    return None


def _stop_loss_pct(entry_price: float, stop_loss: float) -> float:
    if entry_price <= 0:
        return 100.0
    return abs(entry_price - stop_loss) / entry_price * 100


def _entry_valid(
    direction: str,
    entry_price: float,
    stop_loss: float,
    broken_level: float,
    config: StrategyConfig,
) -> bool:
    sl_pct = _stop_loss_pct(entry_price, stop_loss)
    if sl_pct < config.min_stop_loss_pct or sl_pct > config.max_stop_loss_pct:
        return False

    distance_pct = abs(entry_price - broken_level) / broken_level * 100 if broken_level else 100.0
    if distance_pct > config.max_entry_distance_from_level_pct:
        return False

    if direction == "long" and (stop_loss >= entry_price or entry_price <= broken_level):
        return False
    if direction == "short" and (stop_loss <= entry_price or entry_price >= broken_level):
        return False
    return True


def _rsi_valid(
    direction: str,
    rsi_values: list[float | None],
    index: int,
    config: StrategyConfig,
) -> bool:
    if not config.use_rsi_filter:
        return True
    if index >= len(rsi_values):
        return False

    rsi = rsi_values[index]
    if rsi is None:
        return False

    if direction == "long":
        return config.rsi_long_min <= rsi <= config.rsi_overbought
    return config.rsi_oversold <= rsi <= config.rsi_short_max


def load_strategy_config(parameters: dict) -> StrategyConfig:
    return StrategyConfig(
        setup_timeframe_minutes=int(parameters.get("setup_timeframe_minutes", 30)),
        entry_timeframe_minutes=int(parameters.get("entry_timeframe_minutes", 5)),
        pivot_left=int(parameters.get("pivot_left", 2)),
        pivot_right=int(parameters.get("pivot_right", 2)),
        retest_tolerance_pct=float(parameters.get("retest_tolerance_pct", 0.15)),
        retest_window_candles=int(parameters.get("retest_window_candles", 36)),
        reward_risk_ratio=float(parameters.get("reward_risk_ratio", 2.0)),
        require_confirmation_candle=bool(parameters.get("require_confirmation_candle", True)),
        min_stop_loss_pct=float(parameters.get("min_stop_loss_pct", 0.05)),
        max_stop_loss_pct=float(parameters.get("max_stop_loss_pct", 1.5)),
        max_entry_distance_from_level_pct=float(
            parameters.get("max_entry_distance_from_level_pct", 0.5)
        ),
        use_rsi_filter=bool(parameters.get("use_rsi_filter", True)),
        rsi_period=int(parameters.get("rsi_period", 14)),
        rsi_long_min=float(parameters.get("rsi_long_min", 50.0)),
        rsi_short_max=float(parameters.get("rsi_short_max", 50.0)),
        rsi_overbought=float(parameters.get("rsi_overbought", 70.0)),
        rsi_oversold=float(parameters.get("rsi_oversold", 30.0)),
        starting_wallet_usd=float(parameters.get("starting_wallet_usd", 10_000)),
    )
