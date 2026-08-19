from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from src.strategy import EntrySignal, StrategyConfig, find_signals, load_strategy_config


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
    take_profit_1: float
    take_profit_2: float
    liquidity_price: float
    liquidity_kind: str
    entry_lots: int
    lots: int
    points: float
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
    sweeps_detected: int
    confirmed_entries: int
    backtest_mode: str = "liquidity_sweep_trap"
    rule_compliance: dict[str, bool] | None = None


def _return_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        raw = ((exit_price - entry_price) / entry_price) * 100
    else:
        raw = ((entry_price - exit_price) / entry_price) * 100
    return max(raw, -100.0)


def _points_captured(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return exit_price - entry_price
    return entry_price - exit_price


def _trade_type(side: str) -> str:
    return "Buy" if side == "long" else "Sell"


def _apply_return(equity: float, return_pct: float, lots: int, position_lots: int) -> float:
    weight = lots / position_lots if position_lots else 1.0
    return equity * (1 + (return_pct * weight) / 100)


def _append_leg(
    trades: list[Trade],
    signal: EntrySignal,
    *,
    exit_date: str,
    exit_price: float,
    exit_reason: str,
    lots: int,
    starting_wallet: float,
    equity: float,
) -> None:
    return_pct = _return_pct(signal.direction, signal.entry_price, exit_price)
    trades.append(
        Trade(
            entry_date=signal.entry_timestamp[:16],
            exit_date=exit_date[:16],
            entry_price=round(signal.entry_price, 2),
            exit_price=round(exit_price, 2),
            return_pct=round(return_pct, 2),
            exit_reason=exit_reason,
            side=signal.direction,
            trade_type=_trade_type(signal.direction),
            stop_loss=round(signal.stop_loss, 2),
            take_profit_1=round(signal.take_profit_1, 2),
            take_profit_2=round(signal.take_profit_2, 2),
            liquidity_price=round(signal.liquidity_price, 2),
            liquidity_kind=signal.liquidity_kind,
            entry_lots=signal.position_lots,
            lots=lots,
            points=round(_points_captured(signal.direction, signal.entry_price, exit_price), 2),
            wallet_balance=round(starting_wallet * equity, 2),
        )
    )


def _hit_stop(signal: EntrySignal, high: float, low: float) -> bool:
    if signal.direction == "long":
        return low <= signal.stop_loss
    return high >= signal.stop_loss


def _hit_target(signal: EntrySignal, high: float, low: float, target: float) -> bool:
    if signal.direction == "long":
        return high >= target
    return low <= target


def _simulate_trade(
    ltf_rows: list[dict],
    signal: EntrySignal,
    config: StrategyConfig,
    starting_wallet: float,
    equity: float,
) -> tuple[list[Trade], float, datetime | None]:
    entry_ts = datetime.fromisoformat(signal.entry_timestamp)
    start_index = next(
        (
            index
            for index, row in enumerate(ltf_rows)
            if datetime.fromisoformat(row["timestamp"]) >= entry_ts
        ),
        None,
    )
    if start_index is None:
        return [], equity, None

    legs: list[Trade] = []
    remaining = signal.position_lots
    partial_taken = False
    last_index = min(len(ltf_rows) - 1, start_index + config.max_hold_candles)

    for index in range(start_index + 1, last_index + 1):
        row = ltf_rows[index]
        high = float(row["high"])
        low = float(row["low"])
        timestamp = row["timestamp"]

        if _hit_stop(signal, high, low):
            return_pct = _return_pct(signal.direction, signal.entry_price, signal.stop_loss)
            equity = _apply_return(equity, return_pct, remaining, signal.position_lots)
            _append_leg(
                legs,
                signal,
                exit_date=timestamp,
                exit_price=signal.stop_loss,
                exit_reason="stop_loss",
                lots=remaining,
                starting_wallet=starting_wallet,
                equity=equity,
            )
            return legs, equity, datetime.fromisoformat(timestamp)

        if not partial_taken and _hit_target(signal, high, low, signal.take_profit_1):
            return_pct = _return_pct(signal.direction, signal.entry_price, signal.take_profit_1)
            equity = _apply_return(
                equity, return_pct, signal.partial_exit_lots, signal.position_lots
            )
            _append_leg(
                legs,
                signal,
                exit_date=timestamp,
                exit_price=signal.take_profit_1,
                exit_reason="partial_5pts",
                lots=signal.partial_exit_lots,
                starting_wallet=starting_wallet,
                equity=equity,
            )
            remaining = signal.runner_lots
            partial_taken = True

        if partial_taken and remaining > 0 and _hit_target(signal, high, low, signal.take_profit_2):
            return_pct = _return_pct(signal.direction, signal.entry_price, signal.take_profit_2)
            equity = _apply_return(equity, return_pct, remaining, signal.position_lots)
            _append_leg(
                legs,
                signal,
                exit_date=timestamp,
                exit_price=signal.take_profit_2,
                exit_reason="take_profit_15pts",
                lots=remaining,
                starting_wallet=starting_wallet,
                equity=equity,
            )
            return legs, equity, datetime.fromisoformat(timestamp)

    last = ltf_rows[last_index]
    exit_price = float(last["close"])
    reason = "time_stop" if last_index < len(ltf_rows) - 1 else "open_at_end"
    return_pct = _return_pct(signal.direction, signal.entry_price, exit_price)
    equity = _apply_return(equity, return_pct, remaining, signal.position_lots)
    _append_leg(
        legs,
        signal,
        exit_date=last["timestamp"],
        exit_price=exit_price,
        exit_reason=reason,
        lots=remaining,
        starting_wallet=starting_wallet,
        equity=equity,
    )
    return legs, equity, datetime.fromisoformat(last["timestamp"])


def backtest_liquidity_sweep_trap(ltf_rows: list[dict], rule: dict) -> BacktestResult:
    config = load_strategy_config(rule.get("parameters", {}))
    signals, sweeps_detected = find_signals(ltf_rows, config)

    trades: list[Trade] = []
    equity = 1.0
    equity_curve = [equity]
    last_exit_ts: datetime | None = None
    confirmed_entries = 0

    for signal in signals:
        entry_ts = datetime.fromisoformat(signal.entry_timestamp)
        if last_exit_ts and entry_ts <= last_exit_ts:
            continue

        confirmed_entries += 1
        legs, equity, exit_ts = _simulate_trade(
            ltf_rows,
            signal,
            config,
            config.starting_wallet_usd,
            equity,
        )
        if not legs:
            continue

        trades.extend(legs)
        last_exit_ts = exit_ts
        equity_curve.append(equity)

    return _build_result(rule, trades, equity_curve, ltf_rows, sweeps_detected, confirmed_entries)


def _position_net_points(trades: list[Trade]) -> list[float]:
    grouped: dict[tuple[str, str], float] = {}
    for trade in trades:
        key = (trade.entry_date, trade.side)
        grouped[key] = grouped.get(key, 0.0) + (trade.points * trade.lots)
    return list(grouped.values())


def _build_result(
    rule: dict,
    trades: list[Trade],
    equity: list[float],
    rows: list[dict],
    sweeps_detected: int,
    confirmed_entries: int,
) -> BacktestResult:
    nets = _position_net_points(trades)
    total_trades = len(nets)
    wins = sum(1 for value in nets if value > 0)
    win_rate = (wins / total_trades * 100) if total_trades else 0.0
    avg_return = sum(trade.return_pct for trade in trades) / len(trades) if trades else 0.0
    total_return = ((equity[-1] - 1) * 100) if equity else 0.0

    first_close = float(rows[0]["close"])
    last_close = float(rows[-1]["close"])
    buy_hold = ((last_close - first_close) / first_close) * 100 if first_close else 0.0

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
        "finds_htf_liquidity": True,
        "waits_for_price_to_reach_zone": True,
        "requires_sweep_not_touch": True,
        "requires_confirmation_before_entry": True,
        "enters_100_lots": int(params.get("position_lots", 100)) == 100,
        "partial_50pct_at_5_points": int(params.get("partial_exit_lots", 50)) == 50
        and float(params.get("partial_target_points", 5)) == 5,
        "runner_50pct_at_15_points": int(params.get("runner_lots", 50)) == 50
        and float(params.get("runner_target_points", 15)) == 15,
        "supports_long_and_short": True,
    }

    return BacktestResult(
        rule_name=rule.get("name", "Liquidity Sweep Trap"),
        strategy_type=rule.get("strategy_type", "liquidity_sweep_trap"),
        total_trades=total_trades,
        win_rate=round(win_rate, 2),
        total_return_pct=round(total_return, 2),
        buy_hold_return_pct=round(buy_hold, 2),
        max_drawdown_pct=round(max_drawdown, 2),
        avg_return_pct=round(avg_return, 2),
        verdict=verdict,
        trades=trades,
        sweeps_detected=sweeps_detected,
        confirmed_entries=confirmed_entries,
        rule_compliance=compliance,
    )


def result_to_dict(result: BacktestResult) -> dict:
    return asdict(result)
