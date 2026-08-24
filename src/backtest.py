from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from src.poc_strategy import (
    PocState,
    group_bars_by_day,
    process_m15_bar,
    sync_session_state,
)
from src.risk import day_loss_reached, fill_risk_allowed, lots_for_risk, reached_r


SECONDS_PER_DAY = 86400.0


@dataclass
class BacktestParams:
    target_points: float = 15.0
    position_lots: int = 100
    fee_pct_per_side: float = 0.05
    starting_wallet_usd: float = 10000.0
    usd_per_point_per_lot: float = 0.01
    min_sl_points: float = 5.0
    max_sl_points: float = 10.0
    min_reward_to_risk: float = 1.5
    reward_r_multiple: float = 2.0
    use_session_filter: bool = True
    session_start_hour_utc: int = 8
    session_end_hour_utc: int = 20
    max_trades_per_day: int = 4
    use_htf_bias: bool = True
    use_risk_sizing: bool = True
    risk_pct_per_trade: float = 1.0
    min_lots: int = 1
    daily_loss_pct: float = 3.0
    max_leverage: float = 1.0
    move_stop_to_breakeven: bool = True
    breakeven_r_multiple: float = 1.5
    warmup_days: float = 1.0
    bin_size: float = 1.0
    value_area_pct: float = 0.70
    touch_points: float = 2.0
    trade_poc: bool = True
    trade_val: bool = False
    trade_vah: bool = False
    require_return: bool = True
    min_away_points: float = 12.0
    min_sweep_points: float = 2.0
    min_close_beyond: float = 2.0
    min_body_points: float = 0.0
    require_open_pullback: bool = True
    max_intraday_range: float = 100.0
    skip_monday: bool = True


@dataclass
class OpenPosition:
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    lots: int
    level: float
    entry_line: str
    original_stop: float = 0.0
    breakeven_done: bool = False

    def __post_init__(self) -> None:
        if self.original_stop == 0.0:
            self.original_stop = self.stop_loss


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


def params_from_rule(parameters: dict) -> BacktestParams:
    return BacktestParams(
        target_points=float(parameters.get("partial_target_points", 15)),
        position_lots=int(parameters.get("position_lots", 100)),
        fee_pct_per_side=float(parameters.get("fee_pct_per_side", 0.05)),
        starting_wallet_usd=float(parameters.get("starting_wallet_usd", 10000)),
        usd_per_point_per_lot=float(parameters.get("usd_per_point_per_lot", 0.01)),
        min_sl_points=float(parameters.get("min_stop_loss_points", 5.0)),
        max_sl_points=float(parameters.get("max_stop_loss_points", 10.0)),
        min_reward_to_risk=float(parameters.get("min_reward_to_risk", 1.5)),
        reward_r_multiple=float(parameters.get("reward_r_multiple", 2.0)),
        use_session_filter=bool(parameters.get("use_session_filter", True)),
        session_start_hour_utc=int(parameters.get("session_start_hour_utc", 8)),
        session_end_hour_utc=int(parameters.get("session_end_hour_utc", 20)),
        max_trades_per_day=int(parameters.get("max_trades_per_sequence", 4)),
        use_htf_bias=bool(parameters.get("use_htf_bias", True)),
        use_risk_sizing=bool(parameters.get("use_risk_sizing", True)),
        risk_pct_per_trade=float(parameters.get("risk_pct_per_trade", 1.0)),
        min_lots=int(parameters.get("min_lots", 1)),
        daily_loss_pct=float(parameters.get("daily_loss_pct", 3.0)),
        max_leverage=float(parameters.get("max_leverage", 1.0)),
        move_stop_to_breakeven=bool(parameters.get("move_stop_to_breakeven", True)),
        breakeven_r_multiple=float(parameters.get("breakeven_r_multiple", 1.5)),
        warmup_days=float(parameters.get("warmup_days", 1.0)),
        bin_size=float(parameters.get("bin_size", 1.0)),
        value_area_pct=float(parameters.get("value_area_pct", 0.70)),
        touch_points=float(parameters.get("touch_points", 2.0)),
        trade_poc=bool(parameters.get("trade_poc", True)),
        trade_val=bool(parameters.get("trade_val", False)),
        trade_vah=bool(parameters.get("trade_vah", False)),
        require_return=bool(parameters.get("require_return", True)),
        min_away_points=float(parameters.get("min_away_points", 12.0)),
        min_sweep_points=float(parameters.get("min_sweep_points", 2.0)),
        min_close_beyond=float(parameters.get("min_close_beyond", 2.0)),
        min_body_points=float(parameters.get("min_body_points", 0.0)),
        require_open_pullback=bool(parameters.get("require_open_pullback", True)),
        max_intraday_range=float(parameters.get("max_intraday_range", 100.0)),
        skip_monday=bool(parameters.get("skip_monday", True)),
    )


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()


def _points(side: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if side == "long" else entry - exit_price


def check_bar_exit(position: OpenPosition, row: dict) -> tuple[str, float] | None:
    high = float(row["high"])
    low = float(row["low"])
    if position.side == "long":
        if low <= position.stop_loss:
            return "stop_loss", position.stop_loss
        if high >= position.target:
            return "take_profit", position.target
        return None
    if high >= position.stop_loss:
        return "stop_loss", position.stop_loss
    if low <= position.target:
        return "take_profit", position.target
    return None


def _close_trade(
    position: OpenPosition,
    exit_ts: str,
    exit_price: float,
    reason: str,
    wallet: float,
    params: BacktestParams,
) -> tuple[dict, float]:
    points = _points(position.side, position.entry_price, exit_price)
    rate = params.fee_pct_per_side / 100.0
    size = position.lots * params.usd_per_point_per_lot
    fee = (position.entry_price + exit_price) * size * rate
    net = points * size - fee
    wallet += net
    risk_points = abs(position.entry_price - position.original_stop)
    trade = {
        "side": position.side,
        "entry_ts": position.entry_ts,
        "exit_ts": exit_ts,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_loss": round(position.stop_loss, 4),
        "target": round(position.target, 4),
        "level": round(position.level, 4),
        "entry_line": position.entry_line,
        "lots": position.lots,
        "lot_usd": round(size, 2),
        "size_usd": round(position.entry_price * size, 2),
        "risk_usd": round(risk_points * size, 2),
        "points": round(points, 4),
        "gross_usd": round(points * size, 2),
        "fee_usd": round(fee, 2),
        "net_usd": round(net, 2),
        "reason": reason,
        "wallet": round(wallet, 2),
    }
    return trade, wallet


def _summarize(trades: list[dict], starting_wallet: float) -> BacktestResult:
    ending = trades[-1]["wallet"] if trades else starting_wallet
    points = sum(trade["points"] for trade in trades)
    wins = [trade for trade in trades if trade["net_usd"] > 0]
    losses = [trade for trade in trades if trade["net_usd"] <= 0]
    win_gross = sum(trade["net_usd"] for trade in wins)
    loss_gross = abs(sum(trade["net_usd"] for trade in losses))
    profit_factor = (win_gross / loss_gross) if loss_gross else (float("inf") if win_gross else 0.0)
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
        tp_count=sum(1 for trade in trades if trade["reason"] == "take_profit"),
        sl_count=sum(1 for trade in trades if trade["reason"] == "stop_loss"),
        total_fees=round(sum(trade["fee_usd"] for trade in trades), 2),
        avg_win_points=round(sum(win_points) / len(win_points), 4) if win_points else 0.0,
        avg_loss_points=round(sum(loss_points) / len(loss_points), 4) if loss_points else 0.0,
    )


def _maybe_move_to_breakeven(position: OpenPosition, row: dict, r_multiple: float) -> None:
    if position.breakeven_done:
        return
    if not reached_r(
        position.side,
        position.entry_price,
        position.original_stop,
        float(row["high"]),
        float(row["low"]),
        r_multiple=r_multiple,
    ):
        return
    position.stop_loss = position.entry_price
    position.breakeven_done = True


def _open_from_signal(signal, row: dict, params: BacktestParams, wallet: float) -> OpenPosition | None:
    fill = float(row["close"])
    if not fill_risk_allowed(
        fill,
        signal.stop_loss,
        max_sl_points=params.max_sl_points,
        min_reward_to_risk=params.min_reward_to_risk,
        min_target=params.target_points,
        reward_r=params.reward_r_multiple,
    ):
        return None
    lots = lots_for_risk(
        wallet,
        abs(fill - signal.stop_loss),
        risk_pct=params.risk_pct_per_trade,
        usd_per_point=params.usd_per_point_per_lot,
        min_lots=params.min_lots,
        max_lots=params.position_lots,
        use_risk_sizing=params.use_risk_sizing,
        fallback_lots=params.position_lots,
        entry_price=fill,
        max_leverage=params.max_leverage,
    )
    if lots < 1:
        return None
    return OpenPosition(
        side=signal.side,
        entry_ts=row["timestamp"],
        entry_price=fill,
        stop_loss=signal.stop_loss,
        target=signal.target,
        lots=lots,
        level=signal.level,
        entry_line=signal.entry_line,
        original_stop=signal.stop_loss,
    )


def _trades_on_day(trades: list[dict], day: str) -> int:
    return sum(1 for trade in trades if trade["entry_ts"][:10] == day)


def run_poc_backtest(m15_rows: list[dict], params: BacktestParams | None = None) -> BacktestResult:
    params = params or BacktestParams()
    by_day = group_bars_by_day(m15_rows)
    days = sorted(by_day)
    state = PocState()
    position: OpenPosition | None = None
    trades: list[dict] = []
    wallet = params.starting_wallet_usd
    day_start_wallet = wallet
    trade_start = None
    if params.warmup_days > 0 and m15_rows:
        trade_start = _epoch(m15_rows[0]["timestamp"]) + params.warmup_days * SECONDS_PER_DAY

    for index, day in enumerate(days):
        previous_day = days[index - 1] if index > 0 else None
        previous_bars = by_day[previous_day] if previous_day else None
        sync_session_state(
            state,
            day,
            previous_day,
            previous_bars,
            bin_size=params.bin_size,
            value_area_pct=params.value_area_pct,
        )
        day_start_wallet = wallet
        for row in by_day[day]:
            if trade_start is not None and _epoch(row["timestamp"]) < trade_start:
                continue
            if position is not None:
                exit_hit = check_bar_exit(position, row)
                if exit_hit is not None:
                    reason, exit_price = exit_hit
                    trade, wallet = _close_trade(
                        position, row["timestamp"], exit_price, reason, wallet, params
                    )
                    trades.append(trade)
                    position = None
                elif params.move_stop_to_breakeven:
                    _maybe_move_to_breakeven(position, row, params.breakeven_r_multiple)
                continue
            if params.max_trades_per_day > 0 and _trades_on_day(trades, day) >= params.max_trades_per_day:
                continue
            if day_loss_reached(day_start_wallet, wallet, params.daily_loss_pct):
                continue
            signal = process_m15_bar(
                row,
                state,
                touch_points=params.touch_points,
                min_target=params.target_points,
                reward_r=params.reward_r_multiple,
                min_sl_points=params.min_sl_points,
                max_sl_points=params.max_sl_points,
                min_reward_to_risk=params.min_reward_to_risk,
                use_session_filter=params.use_session_filter,
                session_start_hour_utc=params.session_start_hour_utc,
                session_end_hour_utc=params.session_end_hour_utc,
                use_htf_bias=params.use_htf_bias,
                trade_poc=params.trade_poc,
                trade_val=params.trade_val,
                trade_vah=params.trade_vah,
                require_return=params.require_return,
                min_away_points=params.min_away_points,
                min_sweep_points=params.min_sweep_points,
                min_close_beyond=params.min_close_beyond,
                min_body_points=params.min_body_points,
                require_open_pullback=params.require_open_pullback,
                max_intraday_range=params.max_intraday_range,
                skip_monday=params.skip_monday,
            )
            if signal is None:
                continue
            position = _open_from_signal(signal, row, params, wallet)

    if position is not None and m15_rows:
        last = m15_rows[-1]
        trade, wallet = _close_trade(
            position, last["timestamp"], float(last["close"]), "end_of_data", wallet, params
        )
        trades.append(trade)
    return _summarize(trades, params.starting_wallet_usd)


def run_m15_backtest(m15_rows: list[dict], _m1_rows=None, params: BacktestParams | None = None):
    return run_poc_backtest(m15_rows, params)


def result_to_dict(result: BacktestResult) -> dict:
    return asdict(result)
