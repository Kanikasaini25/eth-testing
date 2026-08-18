from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from src.strategy import (
    BreakEvent,
    EntrySignal,
    StrategyConfig,
    detect_breaks,
    find_retest_entry,
    load_strategy_config,
)


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    exit_reason: str
    side: str
    trade_type: str
    stop_loss: float
    take_profit: float
    broken_level: float
    wallet_balance: float


@dataclass
class BacktestResult:
    rule_name: str
    strategy_type: str
    total_trades: int
    win_rate: float
    total_return_pct: float
    buy_hold_return_pct: float
    max_drawdown_pct: float
    avg_return_pct: float
    verdict: str
    trades: list[Trade]
    breaks_detected: int
    retest_entries: int
    backtest_mode: str = "30m_break_5m_retest"
    rule_compliance: dict[str, bool] | None = None


def _return_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        raw = ((exit_price - entry_price) / entry_price) * 100
    else:
        raw = ((entry_price - exit_price) / entry_price) * 100
    return max(raw, -100.0)


def _trade_type(side: str) -> str:
    return "Buy" if side == "long" else "Sell"


def _build_trade(
    signal: EntrySignal,
    *,
    entry_date: str,
    exit_date: str,
    entry_price: float,
    exit_price: float,
    return_pct: float,
    exit_reason: str,
    starting_wallet: float,
    equity: float,
) -> Trade:
    return Trade(
        entry_date=entry_date,
        exit_date=exit_date,
        entry_price=round(entry_price, 2),
        exit_price=round(exit_price, 2),
        return_pct=round(return_pct, 2),
        exit_reason=exit_reason,
        side=signal.direction,
        trade_type=_trade_type(signal.direction),
        stop_loss=round(signal.stop_loss, 2),
        take_profit=round(signal.take_profit, 2),
        broken_level=round(signal.broken_level, 2),
        wallet_balance=round(starting_wallet * equity, 2),
    )


def _simulate_trade(
    candles_5m: list[dict],
    signal: EntrySignal,
    starting_wallet: float,
    equity: float,
) -> tuple[Trade | None, float, datetime | None]:
    entry_ts = datetime.fromisoformat(signal.entry_timestamp)
    start_index = next(
        (
            index
            for index, row in enumerate(candles_5m)
            if datetime.fromisoformat(row["timestamp"]) >= entry_ts
        ),
        None,
    )
    if start_index is None:
        return None, equity, None

    # Do not evaluate stop/target on the entry candle itself.
    for index in range(start_index + 1, len(candles_5m)):
        row = candles_5m[index]
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        timestamp = row["timestamp"]

        if signal.direction == "long":
            if low <= signal.stop_loss:
                return_pct = _return_pct("long", signal.entry_price, signal.stop_loss)
                equity *= 1 + return_pct / 100
                return (
                    _build_trade(
                        signal,
                        entry_date=signal.entry_timestamp[:16],
                        exit_date=timestamp[:16],
                        entry_price=signal.entry_price,
                        exit_price=signal.stop_loss,
                        return_pct=return_pct,
                        exit_reason="stop_loss",
                        starting_wallet=starting_wallet,
                        equity=equity,
                    ),
                    equity,
                    datetime.fromisoformat(timestamp),
                )
            if high >= signal.take_profit:
                return_pct = _return_pct("long", signal.entry_price, signal.take_profit)
                equity *= 1 + return_pct / 100
                return (
                    _build_trade(
                        signal,
                        entry_date=signal.entry_timestamp[:16],
                        exit_date=timestamp[:16],
                        entry_price=signal.entry_price,
                        exit_price=signal.take_profit,
                        return_pct=return_pct,
                        exit_reason="take_profit",
                        starting_wallet=starting_wallet,
                        equity=equity,
                    ),
                    equity,
                    datetime.fromisoformat(timestamp),
                )
            continue

        if high >= signal.stop_loss:
            return_pct = _return_pct("short", signal.entry_price, signal.stop_loss)
            equity *= 1 + return_pct / 100
            return (
                _build_trade(
                    signal,
                    entry_date=signal.entry_timestamp[:16],
                    exit_date=timestamp[:16],
                    entry_price=signal.entry_price,
                    exit_price=signal.stop_loss,
                    return_pct=return_pct,
                    exit_reason="stop_loss",
                    starting_wallet=starting_wallet,
                    equity=equity,
                ),
                equity,
                datetime.fromisoformat(timestamp),
            )
        if low <= signal.take_profit:
            return_pct = _return_pct("short", signal.entry_price, signal.take_profit)
            equity *= 1 + return_pct / 100
            return (
                _build_trade(
                    signal,
                    entry_date=signal.entry_timestamp[:16],
                    exit_date=timestamp[:16],
                    entry_price=signal.entry_price,
                    exit_price=signal.take_profit,
                    return_pct=return_pct,
                    exit_reason="take_profit",
                    starting_wallet=starting_wallet,
                    equity=equity,
                ),
                equity,
                datetime.fromisoformat(timestamp),
            )

    last = candles_5m[-1]
    exit_price = float(last["close"])
    return_pct = _return_pct(signal.direction, signal.entry_price, exit_price)
    equity *= 1 + return_pct / 100
    return (
        _build_trade(
            signal,
            entry_date=signal.entry_timestamp[:16],
            exit_date=last["timestamp"][:16],
            entry_price=signal.entry_price,
            exit_price=exit_price,
            return_pct=return_pct,
            exit_reason="open_at_end",
            starting_wallet=starting_wallet,
            equity=equity,
        ),
        equity,
        datetime.fromisoformat(last["timestamp"]),
    )


def backtest_swing_break_retest(
    candles_5m: list[dict],
    rule: dict,
) -> BacktestResult:
    config = load_strategy_config(rule.get("parameters", {}))
    breaks = detect_breaks(candles_5m, config)

    trades: list[Trade] = []
    equity = 1.0
    equity_curve = [equity]
    last_exit_ts: datetime | None = None
    retest_entries = 0

    for break_event in breaks:
        break_ts = datetime.fromisoformat(break_event.break_timestamp)
        if last_exit_ts and break_ts <= last_exit_ts:
            continue

        signal = find_retest_entry(candles_5m, break_event, config)
        if signal is None:
            continue

        retest_entries += 1
        trade, equity, exit_ts = _simulate_trade(
            candles_5m,
            signal,
            config.starting_wallet_usd,
            equity,
        )
        if trade is None:
            continue

        trades.append(trade)
        last_exit_ts = exit_ts
        equity_curve.append(equity)

    return _build_result(rule, trades, equity_curve, candles_5m, len(breaks), retest_entries)


def _build_result(
    rule: dict,
    trades: list[Trade],
    equity: list[float],
    rows: list[dict],
    breaks_detected: int,
    retest_entries: int,
) -> BacktestResult:
    total_trades = len(trades)
    wins = sum(1 for trade in trades if trade.return_pct > 0)
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    avg_return = sum(trade.return_pct for trade in trades) / total_trades if total_trades else 0.0

    total_return = ((equity[-1] - 1) * 100) if equity else 0.0
    first_close = float(rows[0]["close"])
    last_close = float(rows[-1]["close"])
    buy_hold = ((last_close - first_close) / first_close) * 100

    rolling_max = equity[0]
    max_drawdown = 0.0
    for value in equity:
        rolling_max = max(rolling_max, value)
        drawdown = ((value - rolling_max) / rolling_max) * 100 if rolling_max else 0.0
        max_drawdown = max(max_drawdown, abs(drawdown))

    if total_trades == 0:
        verdict = "No trades generated"
    elif total_return > 0 and total_return > buy_hold and win_rate >= 50:
        verdict = "Works"
    elif total_return > buy_hold or total_return > 0 or win_rate >= 45:
        verdict = "Mixed"
    else:
        verdict = "Fails"

    params = rule.get("parameters", {})
    compliance = {
        "uses_30m_swing_levels": params.get("setup_timeframe_minutes", 30) == 30,
        "uses_5m_retest_entry": params.get("entry_timeframe_minutes", 5) == 5,
        "long_on_swing_high_break": True,
        "short_on_swing_low_break": True,
        "no_liquidity_concept": True,
        "requires_5m_confirmation_candle": bool(params.get("require_confirmation_candle", True)),
        "filters_min_max_stop_loss": True,
        "supports_long_and_short": True,
    }

    return BacktestResult(
        rule_name=rule.get("name", "Swing Break Retest"),
        strategy_type=rule.get("strategy_type", "swing_break_retest"),
        total_trades=total_trades,
        win_rate=round(win_rate, 2),
        total_return_pct=round(total_return, 2),
        buy_hold_return_pct=round(buy_hold, 2),
        max_drawdown_pct=round(max_drawdown, 2),
        avg_return_pct=round(avg_return, 2),
        verdict=verdict,
        trades=trades,
        breaks_detected=breaks_detected,
        retest_entries=retest_entries,
        rule_compliance=compliance,
    )


def result_to_dict(result: BacktestResult) -> dict:
    return asdict(result)
