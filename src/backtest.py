from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from src.risk import (
    day_loss_reached,
    fill_risk_allowed,
    lots_for_risk,
    reached_one_r,
    target_from_fill,
)
from src.trade_filters import m15_trend, trend_allows
from src.m15_liquidity import (
    M1_SECONDS,
    M15_SECONDS,
    GrabState,
    SwingPoint,
    find_swing_points,
    process_m15_bar,
)


@dataclass
class BacktestParams:
    target_points: float = 15.0
    position_lots: int = 100
    swing_fractal_bars: int = 2
    confirmation_window_bars: int = 15
    fee_pct_per_side: float = 0.05
    starting_wallet_usd: float = 10000.0
    usd_per_point_per_lot: float = 1.0
    require_close_beyond: bool = True
    stop_loss_mode: str = "first_confirmation_candle"
    min_sl_points: float = 5.0
    max_sl_points: float = 10.0
    min_reward_to_risk: float = 1.5
    min_sweep_points: float = 3.0
    reward_r_multiple: float = 2.0
    use_session_filter: bool = True
    session_start_hour_utc: int = 8
    session_end_hour_utc: int = 20
    max_trades_per_day: int = 4
    use_trend_filter: bool = True
    trend_lookback_bars: int = 12
    use_risk_sizing: bool = True
    risk_pct_per_trade: float = 1.0
    min_lots: int = 1
    daily_loss_pct: float = 3.0
    move_stop_to_breakeven: bool = True
    warmup_days: float = 0.0


@dataclass
class OpenPosition:
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    lots: int
    grab_level: float
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
        position_lots=int(parameters.get("position_lots", 20)),
        swing_fractal_bars=int(parameters.get("swing_fractal_bars", 2)),
        confirmation_window_bars=int(parameters.get("confirmation_window_bars", 15)),
        fee_pct_per_side=float(parameters.get("fee_pct_per_side", 0.05)),
        starting_wallet_usd=float(parameters.get("starting_wallet_usd", 10000)),
        require_close_beyond=bool(parameters.get("require_close_beyond", True)),
        stop_loss_mode=str(parameters.get("stop_loss_mode", "first_confirmation_candle")),
        min_sl_points=float(parameters.get("min_stop_loss_points", 5.0)),
        max_sl_points=float(parameters.get("max_stop_loss_points", 10.0)),
        min_reward_to_risk=float(parameters.get("min_reward_to_risk", 1.5)),
        min_sweep_points=float(parameters.get("min_sweep_points", 3.0)),
        reward_r_multiple=float(parameters.get("reward_r_multiple", 2.0)),
        use_session_filter=bool(parameters.get("use_session_filter", True)),
        session_start_hour_utc=int(parameters.get("session_start_hour_utc", 8)),
        session_end_hour_utc=int(parameters.get("session_end_hour_utc", 20)),
        max_trades_per_day=int(parameters.get("max_trades_per_sequence", 4)),
        use_trend_filter=bool(parameters.get("use_trend_filter", True)),
        trend_lookback_bars=int(parameters.get("trend_lookback_bars", 12)),
        use_risk_sizing=bool(parameters.get("use_risk_sizing", True)),
        risk_pct_per_trade=float(parameters.get("risk_pct_per_trade", 1.0)),
        min_lots=int(parameters.get("min_lots", 1)),
        daily_loss_pct=float(parameters.get("daily_loss_pct", 3.0)),
        move_stop_to_breakeven=bool(parameters.get("move_stop_to_breakeven", True)),
        warmup_days=float(parameters.get("warmup_days", 7.0)),
    )


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp).timestamp()


def _points(side: str, entry: float, exit_price: float) -> float:
    if side == "long":
        return exit_price - entry
    return entry - exit_price


def _round_trip_fee(entry: float, exit_price: float, lots: int, params: BacktestParams) -> float:
    rate = params.fee_pct_per_side / 100.0
    size = lots * params.usd_per_point_per_lot
    return (entry + exit_price) * size * rate


def _is_valid_stop(side: str, fill: float, stop_loss: float) -> bool:
    if side == "long":
        return stop_loss < fill
    return stop_loss > fill


def check_bar_exit(position: OpenPosition, row: dict) -> tuple[str, float] | None:
    high = float(row["high"])
    low = float(row["low"])
    if position.side == "long":
        hit_sl = low <= position.stop_loss
        hit_tp = high >= position.target
        if hit_sl:
            return "stop_loss", position.stop_loss
        if hit_tp:
            return "take_profit", position.target
        return None
    hit_sl = high >= position.stop_loss
    hit_tp = low <= position.target
    if hit_sl:
        return "stop_loss", position.stop_loss
    if hit_tp:
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
    gross = points * position.lots * params.usd_per_point_per_lot
    fee = _round_trip_fee(position.entry_price, exit_price, position.lots, params)
    net = gross - fee
    wallet += net
    trade = {
        "side": position.side,
        "entry_ts": position.entry_ts,
        "exit_ts": exit_ts,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_loss": round(position.stop_loss, 4),
        "target": round(position.target, 4),
        "grab_level": round(position.grab_level, 4),
        "entry_line": position.entry_line,
        "lots": position.lots,
        "points": round(points, 4),
        "gross_usd": round(gross, 2),
        "fee_usd": round(fee, 2),
        "net_usd": round(net, 2),
        "reason": reason,
        "wallet": round(wallet, 2),
    }
    return trade, wallet


def _summarize(trades: list[dict], starting_wallet: float) -> BacktestResult:
    ending = trades[-1]["wallet"] if trades else starting_wallet
    points = sum(trade["points"] for trade in trades)
    net = ending - starting_wallet
    wins = [trade for trade in trades if trade["net_usd"] > 0]
    losses = [trade for trade in trades if trade["net_usd"] <= 0]
    win_gross = sum(trade["net_usd"] for trade in wins)
    loss_gross = abs(sum(trade["net_usd"] for trade in losses))
    profit_factor = (win_gross / loss_gross) if loss_gross else (float("inf") if win_gross else 0.0)
    peak = starting_wallet
    max_dd = 0.0
    equity = [{"timestamp": "start", "wallet": starting_wallet}]
    for trade in trades:
        wallet = trade["wallet"]
        peak = max(peak, wallet)
        max_dd = max(max_dd, peak - wallet)
        equity.append({"timestamp": trade["exit_ts"], "wallet": wallet})
    win_points = [trade["points"] for trade in wins]
    loss_points = [trade["points"] for trade in losses]
    return BacktestResult(
        trades=trades,
        equity=equity,
        starting_wallet=starting_wallet,
        ending_wallet=ending,
        net_pnl=round(net, 2),
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


def _append_closed_m15(
    m15_rows: list[dict],
    m15_index: int,
    closed_m15: list[dict],
    bar_close_epoch: float,
) -> int:
    while m15_index < len(m15_rows):
        start = _epoch(m15_rows[m15_index]["timestamp"])
        if start + M15_SECONDS > bar_close_epoch:
            break
        closed_m15.append(m15_rows[m15_index])
        m15_index += 1
    return m15_index


def _maybe_move_to_breakeven(position: OpenPosition, row: dict) -> None:
    if position.breakeven_done:
        return
    if not reached_one_r(
        position.side,
        position.entry_price,
        position.original_stop,
        float(row["high"]),
        float(row["low"]),
    ):
        return
    position.stop_loss = position.entry_price
    position.breakeven_done = True


def _open_from_signal(
    signal,
    row: dict,
    params: BacktestParams,
    wallet: float,
) -> OpenPosition | None:
    fill = float(row["close"])
    if not _is_valid_stop(signal.side, fill, signal.stop_loss):
        return None
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
    )
    if lots < 1:
        return None
    return OpenPosition(
        side=signal.side,
        entry_ts=row["timestamp"],
        entry_price=fill,
        stop_loss=signal.stop_loss,
        target=target_from_fill(
            signal.side,
            fill,
            signal.stop_loss,
            params.target_points,
            params.reward_r_multiple,
        ),
        lots=lots,
        grab_level=signal.grab_level,
        entry_line=signal.entry_line,
        original_stop=signal.stop_loss,
    )


def _trades_on_day(trades: list[dict], day: str) -> int:
    return sum(1 for trade in trades if trade["entry_ts"][:10] == day)


SECONDS_PER_DAY = 86400.0


def _trade_window_start(m1_rows: list[dict], warmup_days: float) -> float | None:
    if warmup_days <= 0 or not m1_rows:
        return None
    return _epoch(m1_rows[0]["timestamp"]) + warmup_days * SECONDS_PER_DAY


def run_m15_backtest(
    m15_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams | None = None,
) -> BacktestResult:
    params = params or BacktestParams()
    fractal = params.swing_fractal_bars
    closed_m15: list[dict] = []
    swings: list[SwingPoint] = []
    m15_index = 0
    last_m15_count = 0
    state = GrabState()
    position: OpenPosition | None = None
    trades: list[dict] = []
    wallet = params.starting_wallet_usd
    day = ""
    day_start_wallet = wallet
    trade_start = _trade_window_start(m1_rows, params.warmup_days)

    for row in m1_rows:
        bar_close = _epoch(row["timestamp"]) + M1_SECONDS
        m15_index = _append_closed_m15(m15_rows, m15_index, closed_m15, bar_close)
        if len(closed_m15) != last_m15_count:
            swings = find_swing_points(closed_m15, left=fractal, right=fractal)
            last_m15_count = len(closed_m15)

        if trade_start is not None and _epoch(row["timestamp"]) < trade_start:
            continue

        row_day = row["timestamp"][:10]
        if row_day != day:
            day = row_day
            day_start_wallet = wallet

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
                _maybe_move_to_breakeven(position, row)
            continue

        if params.max_trades_per_day > 0 and _trades_on_day(trades, row_day) >= params.max_trades_per_day:
            continue
        if day_loss_reached(day_start_wallet, wallet, params.daily_loss_pct):
            continue

        signal = process_m15_bar(
            row,
            swings,
            state,
            target_points=params.target_points,
            confirmation_window_bars=params.confirmation_window_bars,
            require_close_beyond=params.require_close_beyond,
            stop_loss_mode=params.stop_loss_mode,
            min_sl_points=params.min_sl_points,
            max_sl_points=params.max_sl_points,
            min_reward_to_risk=params.min_reward_to_risk,
            min_sweep_points=params.min_sweep_points,
            reward_r=params.reward_r_multiple,
            use_session_filter=params.use_session_filter,
            session_start_hour_utc=params.session_start_hour_utc,
            session_end_hour_utc=params.session_end_hour_utc,
        )
        if signal is None:
            continue
        if params.use_trend_filter:
            trend = m15_trend(closed_m15, params.trend_lookback_bars)
            if not trend_allows(signal.side, trend):
                continue
        position = _open_from_signal(signal, row, params, wallet)

    if position is not None and m1_rows:
        last = m1_rows[-1]
        trade, wallet = _close_trade(
            position, last["timestamp"], float(last["close"]), "end_of_data", wallet, params
        )
        trades.append(trade)

    return _summarize(trades, params.starting_wallet_usd)


def result_to_dict(result: BacktestResult) -> dict:
    return asdict(result)
