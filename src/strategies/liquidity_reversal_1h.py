"""
1H Liquidity Reversal — standalone ETH strategy.

Concept:
  1) Lock confirmed 1H swing high / swing low as liquidity levels (no moving once set).
  2) Wait for a liquidity sweep of one level.
  3) On 1m, wait for a 2-candle same-color reversal that breaks the first candle.
  4) Enter on the break; SL = first confirmation candle wick.
  5) At +15 points: book 80 lots; keep 20 lots with a trailing stop.

This module does NOT modify or depend on the LQDTY / YouTube liquidity strategy.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable

from src.backtest import (
    ETH_PER_LOT,
    FIXED_ENTRY_LOTS,
    PARTIAL_EXIT_LOTS,
    RUNNER_LOTS,
    BacktestResult,
    Trade,
    _build_result,
    _close_trade,
    _trading_fee_usd,
)
from src.rule_extractor import TradingRule

STRATEGY_NAME = "1H Liquidity Reversal"
STRATEGY_TYPE = "liquidity_reversal_1h"
TAKE_PROFIT_POINTS = 15.0
TRAILING_STOP_POINTS = 3.0
ONE_HOUR = timedelta(hours=1)

logger = logging.getLogger("strategy.1h_liquidity_reversal")


class Phase(str, Enum):
    WAITING_LEVELS = "waiting_levels"
    WAITING_SWEEP = "waiting_sweep"
    WAITING_CONFIRMATION = "waiting_confirmation"
    IN_TRADE = "in_trade"


@dataclass
class SwingPoint:
    index: int
    timestamp: str
    price: float
    confirmed_at: str  # 1H open time of the bar that confirms this swing


@dataclass
class CandleRef:
    timestamp: str
    open: float
    high: float
    low: float
    close: float

    @property
    def is_green(self) -> bool:
        return self.close > self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open


@dataclass
class SetupDebug:
    """Snapshot of the active setup for logging / inspection."""

    swing_high: float | None = None
    swing_high_ts: str | None = None
    swing_low: float | None = None
    swing_low_ts: str | None = None
    sweep_direction: str | None = None
    sweep_ts: str | None = None
    sweep_price: float | None = None
    first_candle: CandleRef | None = None
    second_candle: CandleRef | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    trade_direction: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        first = self.first_candle
        second = self.second_candle
        return {
            "1h_swing_high": self.swing_high,
            "1h_swing_high_ts": self.swing_high_ts,
            "1h_swing_low": self.swing_low,
            "1h_swing_low_ts": self.swing_low_ts,
            "liquidity_sweep": self.sweep_direction is not None,
            "sweep_direction": self.sweep_direction,
            "sweep_ts": self.sweep_ts,
            "sweep_price": self.sweep_price,
            "first_confirmation_candle": (
                {
                    "timestamp": first.timestamp,
                    "open": first.open,
                    "high": first.high,
                    "low": first.low,
                    "close": first.close,
                }
                if first
                else None
            ),
            "second_confirmation_candle": (
                {
                    "timestamp": second.timestamp,
                    "open": second.open,
                    "high": second.high,
                    "low": second.low,
                    "close": second.close,
                }
                if second
                else None
            ),
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "trade_direction": self.trade_direction,
            "notes": list(self.notes),
        }


def build_strategy_rule(**overrides: Any) -> TradingRule:
    """Return a TradingRule describing this strategy (for reports / JSON)."""
    parameters: dict[str, Any] = {
        "instrument": "ETHUSD",
        "setup_timeframe": "1h",
        "entry_timeframe": "1m",
        "swing_strength": 2,
        "take_profit_points": TAKE_PROFIT_POINTS,
        "position_lots": FIXED_ENTRY_LOTS,
        "partial_exit_lots": PARTIAL_EXIT_LOTS,
        "runner_lots": RUNNER_LOTS,
        "trailing_stop_points": TRAILING_STOP_POINTS,
        "use_trailing_stop_after_partial": True,
        "one_trade_at_a_time": True,
        "confirmation_timeout_bars": 120,
        "fee_pct_per_side": 0.05,
        "starting_wallet_usd": 10_000,
        "require_closed_1h_only": True,
    }
    parameters.update(overrides)
    return TradingRule(
        name=STRATEGY_NAME,
        strategy_type=STRATEGY_TYPE,
        setup_rules=[
            "Identify confirmed Swing High and Swing Low on the 1H timeframe.",
            "Lock those levels — do not move them while waiting for a sweep.",
            "Wait for price to sweep (take liquidity beyond) one of the locked levels.",
            "Only after a sweep, switch attention to the 1-minute timeframe.",
        ],
        entry_rules=[
            "LONG: after low-side sweep, wait for first green 1m candle, then second green "
            "that breaks the first candle high. Enter at the break of first green high.",
            "SHORT: after high-side sweep, wait for first red 1m candle, then second red "
            "that breaks the first candle low. Enter at the break of first red low.",
            "Do not enter immediately after the sweep — require the 2-candle confirmation.",
            "Every entry is exactly 100 lots — fixed size.",
            "Only one trade active at a time.",
        ],
        exit_rules=[
            f"At +{int(TAKE_PROFIT_POINTS)} points: book {PARTIAL_EXIT_LOTS} lots (partial take profit).",
            f"Keep {RUNNER_LOTS} lots as runner with a {TRAILING_STOP_POINTS:g}-point trailing stop.",
            "Runner exits only on trailing stop (or end of data) — no second fixed target.",
        ],
        risk_rules=[
            "LONG SL (before partial) = low (wick) of the first green confirmation candle.",
            "SHORT SL (before partial) = high (wick) of the first red confirmation candle.",
            "After partial: trailing stop starts at/above (long) or at/below (short) entry "
            f"and trails by {TRAILING_STOP_POINTS:g} points from best price.",
            "No EMA, RSI, MACD, Bollinger, or other indicators.",
        ],
        parameters=parameters,
        source_quotes=[],
    )


def _parse_ts(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _candle_from_row(row: dict) -> CandleRef:
    return CandleRef(
        timestamp=row["timestamp"],
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
    )


def _closed_1h_cutoff(minute_ts: str) -> datetime:
    """
    Latest 1H candle open time that is fully closed at this 1m bar.

    A 1H candle with open time T covers [T, T+1h) and is only known after T+1h.
    Using open_time <= minute_open - 1h avoids look-ahead on the forming hour.
    """
    return _parse_ts(minute_ts) - ONE_HOUR


def find_confirmed_swings(
    hour_rows: list[dict],
    *,
    strength: int = 2,
) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    Fractal swing highs/lows on closed 1H bars.

    A swing at index i is confirmed only after `strength` bars to the right close.
    confirmed_at = open timestamp of bar i + strength (the confirming bar).
    """
    if strength < 1:
        raise ValueError("swing strength must be >= 1")

    highs = [float(row["high"]) for row in hour_rows]
    lows = [float(row["low"]) for row in hour_rows]
    swing_highs: list[SwingPoint] = []
    swing_lows: list[SwingPoint] = []

    for index in range(strength, len(hour_rows) - strength):
        left = range(index - strength, index)
        right = range(index + 1, index + strength + 1)
        high = highs[index]
        low = lows[index]

        if all(high > highs[j] for j in left) and all(high > highs[j] for j in right):
            confirm_idx = index + strength
            swing_highs.append(
                SwingPoint(
                    index=index,
                    timestamp=hour_rows[index]["timestamp"],
                    price=high,
                    confirmed_at=hour_rows[confirm_idx]["timestamp"],
                )
            )

        if all(low < lows[j] for j in left) and all(low < lows[j] for j in right):
            confirm_idx = index + strength
            swing_lows.append(
                SwingPoint(
                    index=index,
                    timestamp=hour_rows[index]["timestamp"],
                    price=low,
                    confirmed_at=hour_rows[confirm_idx]["timestamp"],
                )
            )

    return swing_highs, swing_lows


def _latest_confirmed_before(
    swings: list[SwingPoint],
    cutoff_open: datetime,
    *,
    after_open: datetime | None = None,
) -> SwingPoint | None:
    """
    Most recent swing whose confirming 1H bar is fully closed by cutoff_open.

    cutoff_open is the latest allowable 1H *open* time that is closed
    (i.e. minute_time - 1h). A swing confirmed on bar C is known when C is closed,
    i.e. when cutoff_open >= C.open.
    """
    chosen: SwingPoint | None = None
    for swing in swings:
        confirmed_open = _parse_ts(swing.confirmed_at)
        if confirmed_open > cutoff_open:
            continue
        swing_open = _parse_ts(swing.timestamp)
        if after_open is not None and swing_open <= after_open:
            continue
        chosen = swing
    return chosen


def _log(debug: bool, message: str, *args: Any) -> None:
    if debug:
        logger.info(message, *args)


def backtest_1h_liquidity_reversal(
    minute_rows: list[dict],
    hour_rows: list[dict],
    rule: TradingRule | None = None,
    *,
    debug: bool = True,
    on_event: Callable[[str, dict[str, Any]], None] | None = None,
) -> BacktestResult:
    """
    Backtest the 1H Liquidity Reversal strategy on ETH 1m + 1h OHLCV.

    Anti look-ahead:
      - 1H swings use only fully closed hourly candles relative to each 1m bar.
      - Swing confirmation requires `strength` bars to the right before the level exists.
      - Locked swing levels are never updated while waiting for sweep/confirmation.
      - Entries use the break price of the first confirmation candle, only after the
        second candle proves the break with matching color.
    """
    rule = rule or build_strategy_rule()
    params = rule.parameters
    strength = int(params.get("swing_strength", 2))
    tp_points = float(params.get("take_profit_points", TAKE_PROFIT_POINTS))
    position_lots = int(params.get("position_lots", FIXED_ENTRY_LOTS))
    partial_exit_lots = int(
        params.get(
            "partial_exit_lots",
            position_lots * PARTIAL_EXIT_LOTS // FIXED_ENTRY_LOTS,
        )
    )
    runner_lots = int(params.get("runner_lots", position_lots - partial_exit_lots))
    if partial_exit_lots + runner_lots != position_lots:
        runner_lots = position_lots - partial_exit_lots
    trailing_stop_points = float(
        params.get("trailing_stop_points", TRAILING_STOP_POINTS)
    )
    use_trailing_after_partial = bool(
        params.get("use_trailing_stop_after_partial", True)
    )
    timeout_bars = int(params.get("confirmation_timeout_bars", 120))
    fee_pct = float(params.get("fee_pct_per_side", 0.05))
    starting_wallet = float(params.get("starting_wallet_usd", 10_000))
    partial_exit_reason = f"partial_target_{int(tp_points)}pts"

    swing_highs, swing_lows = find_confirmed_swings(hour_rows, strength=strength)
    _log(
        debug,
        "Precomputed %s swing highs and %s swing lows (strength=%s) from %s 1H bars",
        len(swing_highs),
        len(swing_lows),
        strength,
        len(hour_rows),
    )

    trades: list[Trade] = []
    wallet_usd = starting_wallet
    equity_curve = [wallet_usd / starting_wallet]
    setup_log: list[dict[str, Any]] = []

    phase = Phase.WAITING_LEVELS
    locked_high: SwingPoint | None = None
    locked_low: SwingPoint | None = None
    # After a completed cycle, only accept newer swings than these opens.
    min_swing_open_high: datetime | None = None
    min_swing_open_low: datetime | None = None

    sweep_side: str | None = None  # "long" after low sweep, "short" after high sweep
    sweep_ts: str | None = None
    sweep_price: float | None = None
    bars_since_sweep = 0
    first_candle: CandleRef | None = None

    in_position = False
    side = ""
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    entry_ts = ""
    entry_fee_remaining = 0.0
    open_lots = 0
    partial_taken = False
    runner_open = False
    best_price = 0.0
    active_debug = SetupDebug()

    def emit(event: str, payload: dict[str, Any]) -> None:
        if on_event is not None:
            on_event(event, payload)
        if debug:
            logger.info("[%s] %s", event, payload)

    def flat_position() -> None:
        nonlocal in_position, side, partial_taken, runner_open, best_price, open_lots
        in_position = False
        side = ""
        partial_taken = False
        runner_open = False
        best_price = 0.0
        open_lots = 0

    def record_exit(
        ts: str,
        exit_price: float,
        reason: str,
        lots: int,
    ) -> None:
        nonlocal wallet_usd, entry_fee_remaining, open_lots
        wallet_usd, entry_fee_remaining, open_lots = _close_trade(
            trades,
            wallet_usd,
            entry_ts,
            ts,
            entry_price,
            exit_price,
            reason,
            side,
            lots,
            position_lots,
            entry_fee_remaining,
            open_lots,
            fee_pct_per_side=fee_pct,
        )
        emit(
            "trade_closed",
            {
                "timestamp": ts,
                "side": side,
                "entry": entry_price,
                "exit": exit_price,
                "lots": lots,
                "reason": reason,
                "partial_taken": partial_taken,
                "setup": active_debug.to_dict(),
            },
        )
        setup_log.append(
            {
                "event": "trade_closed",
                "timestamp": ts,
                "side": side,
                "entry": entry_price,
                "exit": exit_price,
                "lots": lots,
                "reason": reason,
                "setup": active_debug.to_dict(),
            }
        )

    def activate_runner_after_partial(ts: str, bar_high: float, bar_low: float) -> None:
        """Book partial at TP, then trail the remaining runner lots."""
        nonlocal partial_taken, runner_open, best_price, stop_loss, open_lots
        nonlocal wallet_usd, entry_fee_remaining
        record_exit(ts, take_profit, partial_exit_reason, partial_exit_lots)
        partial_taken = True
        runner_open = True
        if side == "long":
            best_price = max(take_profit, bar_high)
            stop_loss = (
                max(entry_price, best_price - trailing_stop_points)
                if use_trailing_after_partial
                else entry_price
            )
        else:
            best_price = min(take_profit, bar_low)
            stop_loss = (
                min(entry_price, best_price + trailing_stop_points)
                if use_trailing_after_partial
                else entry_price
            )
        active_debug.stop_loss = stop_loss
        active_debug.notes.append(
            f"Partial {partial_exit_lots} lots @ {take_profit}; "
            f"runner {runner_lots} lots trailing SL={stop_loss}"
        )
        emit(
            "partial_taken",
            {
                "timestamp": ts,
                "partial_lots": partial_exit_lots,
                "runner_lots": runner_lots,
                "trailing_sl": stop_loss,
                "setup": active_debug.to_dict(),
            },
        )

    def manage_open_trade(candle: CandleRef) -> bool:
        """
        Manage open position for this 1m bar.

        Returns True if the full position is flat (cycle complete).
        """
        nonlocal stop_loss, best_price, partial_taken, runner_open

        high = candle.high
        low = candle.low
        ts = candle.timestamp

        if side == "long":
            if partial_taken and runner_open and use_trailing_after_partial:
                best_price = max(best_price, high)
                stop_loss = max(entry_price, best_price - trailing_stop_points)
                active_debug.stop_loss = stop_loss

            hit_tp = (not partial_taken) and high >= take_profit
            hit_sl = low <= stop_loss

            if not partial_taken and hit_sl and hit_tp:
                record_exit(
                    ts, stop_loss, "stop_loss_same_bar_priority", position_lots
                )
                flat_position()
                return True

            if not partial_taken and hit_tp:
                activate_runner_after_partial(ts, high, low)
                # Same bar may also tag the new trailing stop after partial.
                if low <= stop_loss:
                    reason = (
                        "trailing_stop"
                        if use_trailing_after_partial and stop_loss > entry_price
                        else "breakeven_stop"
                        if stop_loss == entry_price
                        else "stop_loss"
                    )
                    record_exit(ts, stop_loss, reason, runner_lots)
                    flat_position()
                    return True
                return False

            if hit_sl:
                if partial_taken and use_trailing_after_partial and stop_loss > entry_price:
                    reason = "trailing_stop"
                elif partial_taken and stop_loss == entry_price:
                    reason = "breakeven_stop"
                else:
                    reason = "stop_loss"
                exit_lots = runner_lots if partial_taken else position_lots
                record_exit(ts, stop_loss, reason, exit_lots)
                flat_position()
                return True
            return False

        # short
        if partial_taken and runner_open and use_trailing_after_partial:
            best_price = min(best_price, low) if best_price > 0 else low
            stop_loss = min(entry_price, best_price + trailing_stop_points)
            active_debug.stop_loss = stop_loss

        hit_tp = (not partial_taken) and low <= take_profit
        hit_sl = high >= stop_loss

        if not partial_taken and hit_sl and hit_tp:
            record_exit(ts, stop_loss, "stop_loss_same_bar_priority", position_lots)
            flat_position()
            return True

        if not partial_taken and hit_tp:
            activate_runner_after_partial(ts, high, low)
            if high >= stop_loss:
                reason = (
                    "trailing_stop"
                    if use_trailing_after_partial and stop_loss < entry_price
                    else "breakeven_stop"
                    if stop_loss == entry_price
                    else "stop_loss"
                )
                record_exit(ts, stop_loss, reason, runner_lots)
                flat_position()
                return True
            return False

        if hit_sl:
            if partial_taken and use_trailing_after_partial and stop_loss < entry_price:
                reason = "trailing_stop"
            elif partial_taken and stop_loss == entry_price:
                reason = "breakeven_stop"
            else:
                reason = "stop_loss"
            exit_lots = runner_lots if partial_taken else position_lots
            record_exit(ts, stop_loss, reason, exit_lots)
            flat_position()
            return True
        return False

    def open_position(
        *,
        trade_side: str,
        price: float,
        sl: float,
        tp: float,
        ts: str,
        candle: CandleRef,
    ) -> bool:
        """
        Open a new position. Returns True if the cycle already completed on the entry bar.
        """
        nonlocal in_position, side, entry_price, stop_loss, take_profit, entry_ts
        nonlocal entry_fee_remaining, open_lots, wallet_usd, phase
        nonlocal partial_taken, runner_open, best_price

        side = trade_side
        entry_price = price
        stop_loss = sl
        take_profit = tp
        entry_ts = ts
        in_position = True
        phase = Phase.IN_TRADE
        partial_taken = False
        runner_open = False
        best_price = 0.0
        open_lots = position_lots
        entry_fee_remaining = _trading_fee_usd(entry_price, position_lots, fee_pct)
        wallet_usd -= entry_fee_remaining
        active_debug.entry_price = entry_price
        active_debug.stop_loss = stop_loss
        active_debug.take_profit = take_profit
        active_debug.trade_direction = trade_side
        active_debug.notes.append(
            f"{trade_side.upper()} entry @ {entry_price}; SL={stop_loss}; "
            f"partial TP={take_profit} ({partial_exit_lots} lots) → "
            f"runner {runner_lots} lots trail {trailing_stop_points:g}pts"
        )
        emit("trade_entered", active_debug.to_dict())
        setup_log.append({"event": "trade_entered", "setup": active_debug.to_dict()})
        return manage_open_trade(candle)

    def reset_levels(reason: str, minute_ts: str) -> None:
        nonlocal phase, locked_high, locked_low, sweep_side, sweep_ts, sweep_price
        nonlocal bars_since_sweep, first_candle, active_debug
        nonlocal min_swing_open_high, min_swing_open_low
        emit(
            "reset_levels",
            {
                "reason": reason,
                "timestamp": minute_ts,
                "previous": active_debug.to_dict(),
            },
        )
        if locked_high is not None:
            min_swing_open_high = _parse_ts(locked_high.timestamp)
        if locked_low is not None:
            min_swing_open_low = _parse_ts(locked_low.timestamp)
        phase = Phase.WAITING_LEVELS
        locked_high = None
        locked_low = None
        sweep_side = None
        sweep_ts = None
        sweep_price = None
        bars_since_sweep = 0
        first_candle = None
        active_debug = SetupDebug(notes=[reason])

    def try_lock_levels(minute_ts: str) -> None:
        nonlocal phase, locked_high, locked_low, active_debug
        cutoff = _closed_1h_cutoff(minute_ts)
        high = _latest_confirmed_before(
            swing_highs, cutoff, after_open=min_swing_open_high
        )
        low = _latest_confirmed_before(
            swing_lows, cutoff, after_open=min_swing_open_low
        )
        if high is None or low is None:
            return
        locked_high = high
        locked_low = low
        phase = Phase.WAITING_SWEEP
        active_debug = SetupDebug(
            swing_high=high.price,
            swing_high_ts=high.timestamp,
            swing_low=low.price,
            swing_low_ts=low.timestamp,
            notes=["Locked confirmed 1H swing high/low; waiting for liquidity sweep"],
        )
        emit(
            "levels_locked",
            {
                "timestamp": minute_ts,
                "1h_cutoff_open": cutoff.isoformat(),
                "setup": active_debug.to_dict(),
            },
        )

    def clear_confirmation(reason: str) -> None:
        nonlocal first_candle
        first_candle = None
        active_debug.first_candle = None
        active_debug.second_candle = None
        active_debug.entry_price = None
        active_debug.stop_loss = None
        active_debug.take_profit = None
        active_debug.notes.append(reason)
        emit("confirmation_reset", {"reason": reason, "setup": active_debug.to_dict()})

    for index, row in enumerate(minute_rows):
        candle = _candle_from_row(row)
        ts = candle.timestamp

        # --- manage open trade ---
        if in_position:
            cycle_done = manage_open_trade(candle)
            if cycle_done:
                reset_levels("cycle_complete", ts)
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        # --- no position: state machine ---
        if phase == Phase.WAITING_LEVELS:
            try_lock_levels(ts)

        if phase == Phase.WAITING_SWEEP and locked_high and locked_low:
            # Sweep must happen on 1m price action vs locked 1H levels.
            if candle.low < locked_low.price:
                sweep_side = "long"
                sweep_ts = ts
                sweep_price = candle.low
                bars_since_sweep = 0
                first_candle = None
                phase = Phase.WAITING_CONFIRMATION
                active_debug.sweep_direction = "low_side"
                active_debug.sweep_ts = ts
                active_debug.sweep_price = sweep_price
                active_debug.trade_direction = "long"
                active_debug.notes.append(
                    f"Low-side liquidity swept below {locked_low.price}; "
                    "waiting for 1m two-green confirmation"
                )
                emit("liquidity_sweep", active_debug.to_dict())
                setup_log.append({"event": "liquidity_sweep", "setup": active_debug.to_dict()})
            elif candle.high > locked_high.price:
                sweep_side = "short"
                sweep_ts = ts
                sweep_price = candle.high
                bars_since_sweep = 0
                first_candle = None
                phase = Phase.WAITING_CONFIRMATION
                active_debug.sweep_direction = "high_side"
                active_debug.sweep_ts = ts
                active_debug.sweep_price = sweep_price
                active_debug.trade_direction = "short"
                active_debug.notes.append(
                    f"High-side liquidity swept above {locked_high.price}; "
                    "waiting for 1m two-red confirmation"
                )
                emit("liquidity_sweep", active_debug.to_dict())
                setup_log.append({"event": "liquidity_sweep", "setup": active_debug.to_dict()})

        elif phase == Phase.WAITING_CONFIRMATION and sweep_side:
            bars_since_sweep += 1
            if timeout_bars > 0 and bars_since_sweep > timeout_bars:
                reset_levels(
                    f"confirmation_timeout_after_{timeout_bars}_bars",
                    ts,
                )
                equity_curve.append(wallet_usd / starting_wallet)
                continue

            # Do not treat the sweep bar itself as confirmation start if it is the sweep print;
            # confirmation begins on subsequent closed 1m candles.
            if sweep_ts is not None and ts == sweep_ts:
                equity_curve.append(wallet_usd / starting_wallet)
                continue

            if sweep_side == "long":
                if first_candle is None:
                    if candle.is_green:
                        first_candle = candle
                        active_debug.first_candle = candle
                        active_debug.notes.append(
                            f"First green candle @ {ts} "
                            f"O={candle.open} H={candle.high} L={candle.low} C={candle.close}"
                        )
                        emit("first_confirmation_candle", active_debug.to_dict())
                    # ignore non-green while waiting for first
                else:
                    # Second candle must be the immediate next 1m bar after first.
                    active_debug.second_candle = candle
                    if not candle.is_green:
                        emit(
                            "setup_rejected",
                            {
                                "reason": "second_candle_not_green",
                                "setup": active_debug.to_dict(),
                            },
                        )
                        setup_log.append(
                            {
                                "event": "setup_rejected",
                                "reason": "second_candle_not_green",
                                "setup": active_debug.to_dict(),
                            }
                        )
                        clear_confirmation("second_candle_not_green")
                    elif candle.high <= first_candle.high:
                        emit(
                            "setup_rejected",
                            {
                                "reason": "second_green_did_not_break_first_high",
                                "first_high": first_candle.high,
                                "second_high": candle.high,
                                "setup": active_debug.to_dict(),
                            },
                        )
                        setup_log.append(
                            {
                                "event": "setup_rejected",
                                "reason": "second_green_did_not_break_first_high",
                                "setup": active_debug.to_dict(),
                            }
                        )
                        clear_confirmation("second_green_did_not_break_first_high")
                    else:
                        entry = first_candle.high
                        sl = first_candle.low
                        tp = entry + tp_points
                        if sl >= entry:
                            clear_confirmation("invalid_sl_not_below_entry")
                        else:
                            cycle_done = open_position(
                                trade_side="long",
                                price=entry,
                                sl=sl,
                                tp=tp,
                                ts=ts,
                                candle=candle,
                            )
                            if cycle_done:
                                reset_levels("cycle_complete", ts)
                            equity_curve.append(wallet_usd / starting_wallet)
                            continue

            elif sweep_side == "short":
                if first_candle is None:
                    if candle.is_red:
                        first_candle = candle
                        active_debug.first_candle = candle
                        active_debug.notes.append(
                            f"First red candle @ {ts} "
                            f"O={candle.open} H={candle.high} L={candle.low} C={candle.close}"
                        )
                        emit("first_confirmation_candle", active_debug.to_dict())
                else:
                    active_debug.second_candle = candle
                    if not candle.is_red:
                        emit(
                            "setup_rejected",
                            {
                                "reason": "second_candle_not_red",
                                "setup": active_debug.to_dict(),
                            },
                        )
                        setup_log.append(
                            {
                                "event": "setup_rejected",
                                "reason": "second_candle_not_red",
                                "setup": active_debug.to_dict(),
                            }
                        )
                        clear_confirmation("second_candle_not_red")
                    elif candle.low >= first_candle.low:
                        emit(
                            "setup_rejected",
                            {
                                "reason": "second_red_did_not_break_first_low",
                                "first_low": first_candle.low,
                                "second_low": candle.low,
                                "setup": active_debug.to_dict(),
                            },
                        )
                        setup_log.append(
                            {
                                "event": "setup_rejected",
                                "reason": "second_red_did_not_break_first_low",
                                "setup": active_debug.to_dict(),
                            }
                        )
                        clear_confirmation("second_red_did_not_break_first_low")
                    else:
                        entry = first_candle.low
                        sl = first_candle.high
                        tp = entry - tp_points
                        if sl <= entry:
                            clear_confirmation("invalid_sl_not_above_entry")
                        else:
                            cycle_done = open_position(
                                trade_side="short",
                                price=entry,
                                sl=sl,
                                tp=tp,
                                ts=ts,
                                candle=candle,
                            )
                            if cycle_done:
                                reset_levels("cycle_complete", ts)
                            equity_curve.append(wallet_usd / starting_wallet)
                            continue

        equity_curve.append(wallet_usd / starting_wallet)

    # Flat open position at end of data (mark at last close).
    if in_position and minute_rows:
        last = minute_rows[-1]
        last_close = float(last["close"])
        remaining = open_lots if open_lots > 0 else (
            runner_lots if partial_taken else position_lots
        )
        record_exit(last["timestamp"], last_close, "end_of_data", remaining)
        flat_position()
        equity_curve.append(wallet_usd / starting_wallet)

    result = _build_result(
        rule,
        trades,
        equity_curve,
        minute_rows or hour_rows,
        entry_based_win_rate=True,
    )
    result.backtest_mode = "1h_swing_liquidity_1m_confirmation"
    result.rule_compliance = {
        "uses_1h_swing_liquidity": True,
        "locks_swing_levels": True,
        "requires_liquidity_sweep_before_1m": True,
        "uses_1m_two_candle_confirmation": True,
        "long_requires_two_green_and_break_high": True,
        "short_requires_two_red_and_break_low": True,
        "long_sl_first_green_low": True,
        "short_sl_first_red_high": True,
        "partial_80_lots_at_15_points": (
            tp_points == 15.0
            and partial_exit_lots == 80
            and runner_lots == 20
        ),
        "runner_20_lots_trailing_stop": use_trailing_after_partial,
        "trailing_stop_points": trailing_stop_points,
        "one_trade_at_a_time": True,
        "no_indicator_filters": True,
        "no_1h_look_ahead": True,
        "setup_events_logged": len(setup_log),
        "eth_contract_size_note": f"1 lot = {ETH_PER_LOT} ETH",
        "debug_event_count": len(setup_log),
    }
    if debug:
        result.rule_compliance["last_setup"] = active_debug.to_dict()
    return result
