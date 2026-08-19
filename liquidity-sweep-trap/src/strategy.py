from __future__ import annotations

from dataclasses import dataclass

from src.liquidity import (
    LiquidityLevel,
    liquidity_at,
    nearest_liquidity,
    resample_ohlcv,
)


@dataclass
class StrategyConfig:
    analysis_tf_minutes: int = 15
    entry_tf_minutes: int = 1
    pivot_left: int = 2
    pivot_right: int = 2
    liquidity_lookback: int = 48
    equal_tolerance_pct: float = 0.15
    min_sweep_beyond_pct: float = 0.03
    max_sweep_beyond_pct: float = 0.6
    confirmation_window_candles: int = 6
    min_confirmation_body_ratio: float = 0.45
    stop_buffer_pct: float = 0.02
    min_stop_loss_pct: float = 0.05
    max_stop_loss_pct: float = 1.2
    max_entry_distance_from_level_pct: float = 0.45
    position_lots: int = 100
    partial_exit_lots: int = 50
    runner_lots: int = 50
    partial_target_points: float = 5.0
    runner_target_points: float = 15.0
    max_hold_candles: int = 30
    starting_wallet_usd: float = 10_000.0


@dataclass
class SweepEvent:
    direction: str
    level: LiquidityLevel
    sweep_price: float
    sweep_timestamp: str
    sweep_index: int
    sweep_close: float


@dataclass
class EntrySignal:
    direction: str
    entry_price: float
    entry_timestamp: str
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    liquidity_price: float
    liquidity_kind: str
    sweep_index: int
    confirm_index: int
    position_lots: int
    partial_exit_lots: int
    runner_lots: int


def load_strategy_config(parameters: dict) -> StrategyConfig:
    return StrategyConfig(
        analysis_tf_minutes=int(parameters.get("analysis_tf_minutes", 15)),
        entry_tf_minutes=int(parameters.get("entry_tf_minutes", 1)),
        pivot_left=int(parameters.get("pivot_left", 2)),
        pivot_right=int(parameters.get("pivot_right", 2)),
        liquidity_lookback=int(parameters.get("liquidity_lookback", 48)),
        equal_tolerance_pct=float(parameters.get("equal_tolerance_pct", 0.15)),
        min_sweep_beyond_pct=float(parameters.get("min_sweep_beyond_pct", 0.03)),
        max_sweep_beyond_pct=float(parameters.get("max_sweep_beyond_pct", 0.6)),
        confirmation_window_candles=int(parameters.get("confirmation_window_candles", 6)),
        min_confirmation_body_ratio=float(parameters.get("min_confirmation_body_ratio", 0.45)),
        stop_buffer_pct=float(parameters.get("stop_buffer_pct", 0.02)),
        min_stop_loss_pct=float(parameters.get("min_stop_loss_pct", 0.05)),
        max_stop_loss_pct=float(parameters.get("max_stop_loss_pct", 1.2)),
        max_entry_distance_from_level_pct=float(
            parameters.get("max_entry_distance_from_level_pct", 0.45)
        ),
        position_lots=int(parameters.get("position_lots", 100)),
        partial_exit_lots=int(parameters.get("partial_exit_lots", 50)),
        runner_lots=int(parameters.get("runner_lots", 50)),
        partial_target_points=float(parameters.get("partial_target_points", 5.0)),
        runner_target_points=float(parameters.get("runner_target_points", 15.0)),
        max_hold_candles=int(parameters.get("max_hold_candles", 30)),
        starting_wallet_usd=float(parameters.get("starting_wallet_usd", 10_000)),
    )


def _body_ratio(row: dict) -> float:
    high = float(row["high"])
    low = float(row["low"])
    candle_range = high - low
    if candle_range <= 0:
        return 0.0
    return abs(float(row["close"]) - float(row["open"])) / candle_range


def _levels_at(htf_rows: list[dict], timestamp: str, config: StrategyConfig) -> list[LiquidityLevel]:
    return liquidity_at(
        htf_rows,
        timestamp,
        tf_minutes=config.analysis_tf_minutes,
        pivot_left=config.pivot_left,
        pivot_right=config.pivot_right,
        lookback=config.liquidity_lookback,
        equal_tolerance_pct=config.equal_tolerance_pct,
    )


def detect_sweep(row: dict, index: int, levels: list[LiquidityLevel], config: StrategyConfig) -> SweepEvent | None:
    """Wick through nearest liquidity, then close back inside — trap, not a breakout."""
    open_price = float(row["open"])
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    nearest_above, nearest_below = nearest_liquidity(levels, open_price)

    long_event = None
    if nearest_below is not None:
        pierce_pct = (nearest_below.price - low) / nearest_below.price * 100
        swept = (
            config.min_sweep_beyond_pct <= pierce_pct <= config.max_sweep_beyond_pct
            and close > nearest_below.price
        )
        if swept:
            long_event = SweepEvent(
                direction="long",
                level=nearest_below,
                sweep_price=low,
                sweep_timestamp=row["timestamp"],
                sweep_index=index,
                sweep_close=close,
            )

    short_event = None
    if nearest_above is not None:
        pierce_pct = (high - nearest_above.price) / nearest_above.price * 100
        swept = (
            config.min_sweep_beyond_pct <= pierce_pct <= config.max_sweep_beyond_pct
            and close < nearest_above.price
        )
        if swept:
            short_event = SweepEvent(
                direction="short",
                level=nearest_above,
                sweep_price=high,
                sweep_timestamp=row["timestamp"],
                sweep_index=index,
                sweep_close=close,
            )

    if long_event and short_event:
        long_pierce = nearest_below.price - low if nearest_below else 0
        short_pierce = high - nearest_above.price if nearest_above else 0
        return long_event if long_pierce >= short_pierce else short_event
    return long_event or short_event


def is_confirmation(row: dict, sweep: SweepEvent, config: StrategyConfig) -> bool:
    """Reversal candle with a real body that closes back beyond the swept level."""
    if _body_ratio(row) < config.min_confirmation_body_ratio:
        return False

    open_price = float(row["open"])
    close = float(row["close"])
    high = float(row["high"])
    low = float(row["low"])

    if sweep.direction == "long":
        if low < sweep.sweep_price:
            return False
        return close > open_price and close > sweep.level.price

    if high > sweep.sweep_price:
        return False
    return close < open_price and close < sweep.level.price


def _points_target(entry_price: float, direction: str, points: float) -> float:
    if direction == "long":
        return entry_price + points
    return entry_price - points


def _stop_loss(sweep: SweepEvent, config: StrategyConfig) -> float:
    buffer = sweep.sweep_price * (config.stop_buffer_pct / 100)
    if sweep.direction == "long":
        return sweep.sweep_price - buffer
    return sweep.sweep_price + buffer


def _entry_valid(signal_like: dict, config: StrategyConfig) -> bool:
    entry_price = signal_like["entry_price"]
    stop_loss = signal_like["stop_loss"]
    liquidity_price = signal_like["liquidity_price"]
    if entry_price <= 0:
        return False

    sl_pct = abs(entry_price - stop_loss) / entry_price * 100
    if sl_pct < config.min_stop_loss_pct or sl_pct > config.max_stop_loss_pct:
        return False

    distance_pct = abs(entry_price - liquidity_price) / liquidity_price * 100
    if distance_pct > config.max_entry_distance_from_level_pct:
        return False

    direction = signal_like["direction"]
    if direction == "long" and stop_loss >= entry_price:
        return False
    if direction == "short" and stop_loss <= entry_price:
        return False
    return True


def find_entry_after_sweep(
    ltf_rows: list[dict],
    sweep: SweepEvent,
    config: StrategyConfig,
) -> EntrySignal | None:
    start = sweep.sweep_index + 1
    end = min(len(ltf_rows), start + config.confirmation_window_candles)

    for index in range(start, end):
        row = ltf_rows[index]
        high = float(row["high"])
        low = float(row["low"])

        if sweep.direction == "long" and low < sweep.sweep_price:
            return None
        if sweep.direction == "short" and high > sweep.sweep_price:
            return None
        if not is_confirmation(row, sweep, config):
            continue

        entry_price = float(row["close"])
        stop_loss = _stop_loss(sweep, config)
        candidate = {
            "direction": sweep.direction,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "liquidity_price": sweep.level.price,
        }
        if not _entry_valid(candidate, config):
            return None

        return EntrySignal(
            direction=sweep.direction,
            entry_price=entry_price,
            entry_timestamp=row["timestamp"],
            stop_loss=stop_loss,
            take_profit_1=_points_target(entry_price, sweep.direction, config.partial_target_points),
            take_profit_2=_points_target(entry_price, sweep.direction, config.runner_target_points),
            liquidity_price=sweep.level.price,
            liquidity_kind=sweep.level.kind,
            sweep_index=sweep.sweep_index,
            confirm_index=index,
            position_lots=config.position_lots,
            partial_exit_lots=config.partial_exit_lots,
            runner_lots=config.runner_lots,
        )

    return None


def find_signals(ltf_rows: list[dict], config: StrategyConfig) -> tuple[list[EntrySignal], int]:
    """Walk entry-timeframe candles: liquidity → sweep/trap → confirmation → entry."""
    htf_rows = resample_ohlcv(ltf_rows, config.analysis_tf_minutes)
    warmup = max(config.pivot_left + config.pivot_right + 3, 12)
    signals: list[EntrySignal] = []
    sweeps_detected = 0
    index = warmup

    while index < len(ltf_rows):
        row = ltf_rows[index]
        levels = _levels_at(htf_rows, row["timestamp"], config)
        if not levels:
            index += 1
            continue

        sweep = detect_sweep(row, index, levels, config)
        if sweep is None:
            index += 1
            continue

        sweeps_detected += 1
        signal = find_entry_after_sweep(ltf_rows, sweep, config)
        if signal is None:
            index += 1
            continue

        signals.append(signal)
        index = signal.confirm_index + 1

    return signals, sweeps_detected
