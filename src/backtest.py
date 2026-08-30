from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from src.config import STRATEGY_FUNDING
from src.strategy import EntrySignal, StrategyParams

MAKER_EXIT_REASONS = {"take_profit"}


def epoch_of(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()


@dataclass
class OpenPosition:
    strategy: str
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    lots: int
    peak: float = 0.0
    funding_pnl: float = 0.0
    entry_rate: float = 0.0


@dataclass
class BacktestResult:
    trades: list[dict] = field(default_factory=list)
    equity: list[dict] = field(default_factory=list)
    starting_wallet: float = 0.0
    ending_wallet: float = 0.0
    net_pnl: float = 0.0
    net_points: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    trade_count: int = 0
    wins: int = 0
    losses: int = 0
    tp_count: int = 0
    sl_count: int = 0
    total_fees: float = 0.0
    avg_win_points: float = 0.0
    avg_loss_points: float = 0.0
    last_close: float = 0.0
    blocked_atr: int = 0
    funding_collected: float = 0.0
    pending_note: str = ""


def _points(side: str, entry: float, exit_price: float) -> float:
    if side in {"carry", "cover", "reverse"}:
        return 0.0
    return exit_price - entry if side == "long" else entry - exit_price


def _hold_minutes(entry_ts: str, exit_ts: str) -> float:
    return max(0.0, (epoch_of(exit_ts) - epoch_of(entry_ts)) / 60.0)


def _fee_parts(
    entry_price: float,
    exit_price: float,
    lots: int,
    reason: str,
    params: StrategyParams,
    extra_legs: int = 0,
) -> tuple[float, float]:
    size = lots * params.contract_value
    taker = params.fee_pct_per_side / 100.0
    maker = params.fee_maker_pct / 100.0
    gst = 1.0 + params.gst_pct / 100.0
    if params.funding_futures_maker:
        entry_rate = maker
        exit_rate = maker
    else:
        entry_rate = maker if params.maker_on_entry else taker
        if params.maker_on_take_profit and reason in MAKER_EXIT_REASONS:
            exit_rate = maker
        else:
            exit_rate = taker
    entry_fee = entry_price * entry_rate * size * gst
    exit_fee = exit_price * exit_rate * size * gst
    # Extra legs (spot hedge) stay taker even when futures are maker.
    spot_entry = extra_legs / 2.0 * entry_price * taker * size * gst if extra_legs else 0.0
    spot_exit = extra_legs / 2.0 * exit_price * taker * size * gst if extra_legs else 0.0
    return entry_fee + spot_entry, exit_fee + spot_exit


def _close_trade(
    position: OpenPosition,
    exit_ts: str,
    exit_price: float,
    reason: str,
    wallet: float,
    params: StrategyParams,
    extra_legs: int = 0,
) -> tuple[dict, float]:
    points = _points(position.side, position.entry_price, exit_price)
    size = position.lots * params.contract_value
    hold = _hold_minutes(position.entry_ts, exit_ts)
    entry_fee, exit_fee = _fee_parts(
        position.entry_price, exit_price, position.lots, reason, params, extra_legs
    )
    fee = entry_fee + exit_fee
    net = points * size - fee + position.funding_pnl
    wallet += net
    trade = {
        "strategy": position.strategy,
        "side": position.side,
        "entry_ts": position.entry_ts,
        "exit_ts": exit_ts,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_loss": round(position.stop_loss, 4),
        "target": round(position.target, 4),
        "lots": position.lots,
        "points": round(points, 4),
        "funding_pnl": round(position.funding_pnl, 4),
        "gross_usd": round(points * size + position.funding_pnl, 2),
        "hold_minutes": round(hold, 2),
        "fee_usd": round(fee, 2),
        "net_usd": round(net, 2),
        "reason": reason,
        "wallet": round(wallet, 2),
        "entry_rate": round(position.entry_rate, 6),
    }
    return trade, wallet


def _summarize(trades: list[dict], starting_wallet: float, **extra) -> BacktestResult:
    ending = trades[-1]["wallet"] if trades else starting_wallet
    points = sum(trade["points"] for trade in trades)
    wins = [trade for trade in trades if trade["net_usd"] > 0]
    losses = [trade for trade in trades if trade["net_usd"] <= 0]
    win_gross = sum(trade["net_usd"] for trade in wins)
    loss_gross = abs(sum(trade["net_usd"] for trade in losses))
    if loss_gross:
        profit_factor = win_gross / loss_gross
    else:
        profit_factor = float("inf") if win_gross else 0.0
    peak = starting_wallet
    max_dd = 0.0
    equity = [{"timestamp": "start", "wallet": starting_wallet}]
    for trade in trades:
        peak = max(peak, trade["wallet"])
        max_dd = max(max_dd, peak - trade["wallet"])
        equity.append({"timestamp": trade["exit_ts"], "wallet": trade["wallet"]})
    win_points = [trade["points"] for trade in wins]
    loss_points = [trade["points"] for trade in losses]
    return BacktestResult(
        trades=trades,
        equity=equity,
        starting_wallet=starting_wallet,
        ending_wallet=ending,
        net_pnl=round(ending - starting_wallet, 2),
        net_points=round(points, 4),
        win_rate=round(len(wins) / len(trades), 4) if trades else 0.0,
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        max_drawdown=round(max_dd, 2),
        trade_count=len(trades),
        wins=len(wins),
        losses=len(losses),
        tp_count=sum(1 for trade in trades if str(trade["reason"]) == "take_profit"),
        sl_count=sum(1 for trade in trades if "stop" in str(trade["reason"])),
        total_fees=round(sum(trade["fee_usd"] for trade in trades), 2),
        avg_win_points=round(sum(win_points) / len(win_points), 4) if win_points else 0.0,
        avg_loss_points=round(sum(loss_points) / len(loss_points), 4) if loss_points else 0.0,
        funding_collected=round(sum(float(trade.get("funding_pnl") or 0) for trade in trades), 2),
        **extra,
    )


def _open_from_signal(signal: EntrySignal, lots: int | None = None) -> OpenPosition:
    size = signal.lots or lots or 0
    return OpenPosition(
        strategy=signal.strategy,
        side=signal.side,
        entry_ts=signal.entry_ts,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target=signal.target,
        lots=size,
        peak=signal.entry_price,
        entry_rate=float(signal.extras.get("funding_rate") or 0.0),
    )


def finish_backtest(
    rows: list[dict],
    trades: list[dict],
    position: OpenPosition | None,
    wallet: float,
    params: StrategyParams,
    extra: dict | None = None,
    extra_legs: int = 0,
) -> BacktestResult:
    extra = extra or {}
    last = rows[-1] if rows else None
    if position is not None and last is not None:
        trade, wallet = _close_trade(
            position, last["timestamp"], float(last["close"]), "end_of_data", wallet, params, extra_legs
        )
        trades.append(trade)
    extra.setdefault("last_close", float(last["close"]) if last is not None else 0.0)
    return _summarize(trades, params.starting_wallet_usd, **extra)


close_trade = _close_trade
open_from_signal = _open_from_signal


def run_backtest(
    rows: list[dict],
    params: StrategyParams,
    funding_rows: list[dict] | None = None,
    entry_log: list[EntrySignal] | None = None,
) -> BacktestResult:
    if params.strategy != STRATEGY_FUNDING:
        raise ValueError(f"Unknown strategy {params.strategy}")
    from src.funding_strategy import run_funding_backtest

    return run_funding_backtest(rows, funding_rows or [], params, entry_log)
