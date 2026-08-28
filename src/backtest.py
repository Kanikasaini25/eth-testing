from __future__ import annotations

from dataclasses import dataclass, field

from src.strategy import (
    EntrySignal,
    PendingSetup,
    confirm_entry,
    detect_liquidity_grab,
    setup_invalidated,
    setup_too_wide,
)
from src.swings import (
    detect_swings,
    epoch_of,
    last_closed_m15_open,
    latest_swing,
    usable_swings,
)


@dataclass
class BacktestParams:
    target_points: float = 30.0
    position_lots: int = 100
    fee_pct_per_side: float = 0.05
    fee_maker_pct: float = 0.02
    maker_on_take_profit: bool = True
    maker_on_entry: bool = False
    scalper_offer: bool = False
    scalper_minutes: float = 30.0
    gst_pct: float = 0.0
    starting_wallet_usd: float = 10000.0
    usd_per_point_per_lot: float = 0.01
    swing_left: int = 2
    swing_right: int = 2
    swing_lookback: int = 48
    confirm_timeout_minutes: int = 90
    sl_buffer_points: float = 1.0
    use_stop_loss: bool = True
    max_sl_points: float = 15.0
    min_sweep_points: float = 3.0
    require_reclaim: bool = True
    require_close_back: bool = True
    grab_on_m15_close: bool = True
    min_confirm_body: float = 1.5
    require_close_break: bool = False
    one_shot_confirm: bool = False
    breakeven_points: float = 0.0
    partial_exit_pct: float = 80.0
    runner_target_points: float = 90.0


@dataclass
class OpenPosition:
    side: str
    entry_ts: str
    entry_price: float
    stop_loss: float
    target: float
    lots: int
    swing_price: float
    sweep_extreme: float
    grab_ts: str
    original_stop: float = 0.0
    breakeven_done: bool = False
    partial_taken: bool = False

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
    grab_count: int = 0
    swing_count: int = 0
    marked_high: float = 0.0
    marked_low: float = 0.0
    last_close: float = 0.0
    pending_side: str = ""
    pending_swing: float = 0.0
    pending_sweep: float = 0.0
    pending_grab_ts: str = ""


def _points(side: str, entry: float, exit_price: float) -> float:
    return exit_price - entry if side == "long" else entry - exit_price


def maybe_move_to_breakeven(position: OpenPosition, row: dict, trigger_points: float) -> None:
    if trigger_points <= 0 or position.breakeven_done:
        return
    high = float(row["high"])
    low = float(row["low"])
    if position.side == "long":
        if low <= position.original_stop:
            return
        if high >= position.entry_price + trigger_points:
            position.stop_loss = position.entry_price
            position.breakeven_done = True
        return
    if high >= position.original_stop:
        return
    if low <= position.entry_price - trigger_points:
        position.stop_loss = position.entry_price
        position.breakeven_done = True


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


MAKER_EXIT_REASONS = {"take_profit", "take_profit_80", "runner_take_profit"}


def _hold_minutes(entry_ts: str, exit_ts: str) -> float:
    return max(0.0, (epoch_of(exit_ts) - epoch_of(entry_ts)) / 60.0)


def _fee_parts(
    entry_price: float,
    exit_price: float,
    lots: int,
    reason: str,
    hold_minutes: float,
    params: BacktestParams,
) -> tuple[float, float, bool]:
    size = lots * params.usd_per_point_per_lot
    taker = params.fee_pct_per_side / 100.0
    maker = params.fee_maker_pct / 100.0
    entry_rate = maker if params.maker_on_entry else taker
    scalped = bool(
        params.scalper_offer and hold_minutes <= params.scalper_minutes
    )
    if scalped:
        exit_rate = 0.0
    elif params.maker_on_take_profit and reason in MAKER_EXIT_REASONS:
        exit_rate = maker
    else:
        exit_rate = taker
    gst = 1.0 + params.gst_pct / 100.0
    entry_fee = entry_price * entry_rate * size * gst
    exit_fee = exit_price * exit_rate * size * gst
    return entry_fee, exit_fee, scalped


def reprice_trades(trades: list[dict], params: BacktestParams) -> list[dict]:
    """Rebuild fees/net/wallet from fills without re-running the strategy."""
    wallet = params.starting_wallet_usd
    sized = params.usd_per_point_per_lot
    out: list[dict] = []
    for trade in trades:
        hold = _hold_minutes(trade["entry_ts"], trade["exit_ts"])
        entry_fee, exit_fee, scalped = _fee_parts(
            float(trade["entry_price"]),
            float(trade["exit_price"]),
            int(trade["lots"]),
            str(trade["reason"]),
            hold,
            params,
        )
        fee = entry_fee + exit_fee
        gross = float(trade["points"]) * int(trade["lots"]) * sized
        net = gross - fee
        wallet += net
        row = dict(trade)
        row["hold_minutes"] = round(hold, 2)
        row["fee_entry_usd"] = round(entry_fee, 4)
        row["fee_exit_usd"] = round(exit_fee, 4)
        row["scalper_applied"] = scalped
        row["gross_usd"] = round(gross, 2)
        row["fee_usd"] = round(fee, 2)
        row["net_usd"] = round(net, 2)
        row["wallet"] = round(wallet, 2)
        out.append(row)
    return out


def _close_trade(
    position: OpenPosition,
    exit_ts: str,
    exit_price: float,
    reason: str,
    wallet: float,
    params: BacktestParams,
) -> tuple[dict, float]:
    points = _points(position.side, position.entry_price, exit_price)
    size = position.lots * params.usd_per_point_per_lot
    hold = _hold_minutes(position.entry_ts, exit_ts)
    entry_fee, exit_fee, scalped = _fee_parts(
        position.entry_price,
        exit_price,
        position.lots,
        reason,
        hold,
        params,
    )
    fee = entry_fee + exit_fee
    net = points * size - fee
    wallet += net
    risk_points = abs(position.entry_price - position.stop_loss)
    trade = {
        "side": position.side,
        "entry_ts": position.entry_ts,
        "exit_ts": exit_ts,
        "entry_price": round(position.entry_price, 4),
        "exit_price": round(exit_price, 4),
        "stop_loss": round(position.stop_loss, 4),
        "target": round(position.target, 4),
        "swing_price": round(position.swing_price, 4),
        "sweep_extreme": round(position.sweep_extreme, 4),
        "grab_ts": position.grab_ts,
        "lots": position.lots,
        "lot_usd": round(size, 2),
        "size_usd": round(position.entry_price * size, 2),
        "risk_usd": round(risk_points * size, 2),
        "points": round(points, 4),
        "gross_usd": round(points * size, 2),
        "hold_minutes": round(hold, 2),
        "fee_entry_usd": round(entry_fee, 4),
        "fee_exit_usd": round(exit_fee, 4),
        "scalper_applied": scalped,
        "fee_usd": round(fee, 2),
        "net_usd": round(net, 2),
        "reason": reason,
        "wallet": round(wallet, 2),
    }
    return trade, wallet


def _scale_out_lots(total: int, pct: float) -> int:
    if pct <= 0 or pct >= 100 or total < 2:
        return 0
    closed = int(total * pct / 100.0)
    return min(max(closed, 1), total - 1)


def _runner_target_price(position: OpenPosition, runner_points: float) -> float:
    if runner_points <= 0:
        offset = 1_000_000.0
    else:
        offset = runner_points
    if position.side == "long":
        return position.entry_price + offset
    return position.entry_price - offset


def _slice_position(position: OpenPosition, lots: int) -> OpenPosition:
    return OpenPosition(
        side=position.side,
        entry_ts=position.entry_ts,
        entry_price=position.entry_price,
        stop_loss=position.stop_loss,
        target=position.target,
        lots=lots,
        swing_price=position.swing_price,
        sweep_extreme=position.sweep_extreme,
        grab_ts=position.grab_ts,
        original_stop=position.original_stop,
        breakeven_done=position.breakeven_done,
        partial_taken=position.partial_taken,
    )


def _manage_open(
    position: OpenPosition,
    bar: dict,
    wallet: float,
    params: BacktestParams,
) -> tuple[OpenPosition | None, list[dict], float]:
    maybe_move_to_breakeven(position, bar, params.breakeven_points)
    exit_hit = check_bar_exit(position, bar)
    if exit_hit is None:
        return position, [], wallet
    reason, exit_price = exit_hit
    closed = _scale_out_lots(position.lots, params.partial_exit_pct)
    if reason == "take_profit" and not position.partial_taken and closed > 0:
        slice_pos = _slice_position(position, closed)
        trade, wallet = _close_trade(
            slice_pos, bar["timestamp"], exit_price, "take_profit_80", wallet, params
        )
        position.lots -= closed
        position.partial_taken = True
        position.stop_loss = position.entry_price
        position.breakeven_done = True
        position.target = _runner_target_price(position, params.runner_target_points)
        if position.side == "long" and float(bar["high"]) >= position.target:
            rest_trade, wallet = _close_trade(
                position, bar["timestamp"], position.target, "runner_take_profit", wallet, params
            )
            return None, [trade, rest_trade], wallet
        if position.side == "short" and float(bar["low"]) <= position.target:
            rest_trade, wallet = _close_trade(
                position, bar["timestamp"], position.target, "runner_take_profit", wallet, params
            )
            return None, [trade, rest_trade], wallet
        return position, [trade], wallet
    label = reason if not position.partial_taken else f"runner_{reason}"
    trade, wallet = _close_trade(
        position, bar["timestamp"], exit_price, label, wallet, params
    )
    return None, [trade], wallet


def _update_runners(
    runners: list[OpenPosition],
    bar: dict,
    wallet: float,
    params: BacktestParams,
) -> tuple[list[OpenPosition], list[dict], float]:
    kept: list[OpenPosition] = []
    fills: list[dict] = []
    for runner in runners:
        left, done, wallet = _manage_open(runner, bar, wallet, params)
        fills.extend(done)
        if left is not None:
            kept.append(left)
    return kept, fills, wallet


def _summarize(
    trades: list[dict],
    starting_wallet: float,
    grab_count: int,
    swing_count: int,
) -> BacktestResult:
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
        tp_count=sum(1 for trade in trades if str(trade["reason"]).startswith("take_profit")),
        sl_count=sum(1 for trade in trades if trade["reason"] == "stop_loss"),
        total_fees=round(sum(trade["fee_usd"] for trade in trades), 2),
        avg_win_points=round(sum(win_points) / len(win_points), 4) if win_points else 0.0,
        avg_loss_points=round(sum(loss_points) / len(loss_points), 4) if loss_points else 0.0,
        grab_count=grab_count,
        swing_count=swing_count,
    )


def _open_position(signal: EntrySignal, lots: int) -> OpenPosition:
    return OpenPosition(
        side=signal.side,
        entry_ts=signal.entry_ts,
        entry_price=signal.entry_price,
        stop_loss=signal.stop_loss,
        target=signal.target,
        lots=lots,
        swing_price=signal.swing_price,
        sweep_extreme=signal.sweep_extreme,
        grab_ts=signal.grab_ts,
    )


def _arm_setup(setup: PendingSetup, bar_epoch: float) -> PendingSetup:
    setup.grab_epoch = bar_epoch
    setup.first_confirm = None
    return setup


def _scan_new_m15_grabs(
    m15_rows: list[dict],
    swings,
    swept_ids: set[str],
    start_index: int,
    end_index: int,
    params: BacktestParams,
    now: float,
) -> tuple[PendingSetup | None, int]:
    grab: PendingSetup | None = None
    count = 0
    for index in range(start_index, end_index + 1):
        if index < 0:
            continue
        available = usable_swings(swings, index, params.swing_lookback, swept_ids)
        found, taken = detect_liquidity_grab(
            m15_rows[index],
            available,
            min_sweep_points=params.min_sweep_points,
            require_close_back=params.require_close_back,
        )
        for swing in taken:
            swept_ids.add(swing.swing_id)
        if found is not None:
            grab = _arm_setup(found, now)
            count += 1
    return grab, count


def run_liquidity_backtest(
    m15_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams | None = None,
    entry_log: list[EntrySignal] | None = None,
) -> BacktestResult:
    params = params or BacktestParams()
    swings = detect_swings(m15_rows, params.swing_left, params.swing_right)
    swept_ids: set[str] = set()
    pending: PendingSetup | None = None
    position: OpenPosition | None = None
    runners: list[OpenPosition] = []
    trades: list[dict] = []
    wallet = params.starting_wallet_usd
    grab_count = 0
    lots = params.position_lots
    m15_epochs = [epoch_of(row["timestamp"]) for row in m15_rows]
    closed_ptr = -1

    for bar in m1_rows:
        now = epoch_of(bar["timestamp"])
        prev_closed = closed_ptr
        closed_open = last_closed_m15_open(now)
        while closed_ptr + 1 < len(m15_epochs) and m15_epochs[closed_ptr + 1] <= closed_open:
            closed_ptr += 1

        runners, runner_fills, wallet = _update_runners(runners, bar, wallet, params)
        trades.extend(runner_fills)

        if params.grab_on_m15_close and closed_ptr > prev_closed and position is None:
            found, added = _scan_new_m15_grabs(
                m15_rows, swings, swept_ids, prev_closed + 1, closed_ptr, params, now
            )
            grab_count += added
            if found is not None:
                pending = found
        elif not params.grab_on_m15_close and position is None:
            available = usable_swings(swings, closed_ptr, params.swing_lookback, swept_ids)
            found, taken = detect_liquidity_grab(
                bar,
                available,
                min_sweep_points=params.min_sweep_points,
                require_close_back=params.require_close_back,
            )
            for swing in taken:
                swept_ids.add(swing.swing_id)
            if found is not None:
                pending = _arm_setup(found, now)
                grab_count += 1

        if position is not None:
            position, fills, wallet = _manage_open(position, bar, wallet, params)
            trades.extend(fills)
            if position is not None and position.partial_taken:
                runners.append(position)
                position = None
            continue

        if pending is None:
            continue
        age_minutes = (now - pending.grab_epoch) / 60.0
        if age_minutes > params.confirm_timeout_minutes:
            pending = None
            continue
        if setup_invalidated(pending, bar) or (
            params.use_stop_loss
            and setup_too_wide(pending, params.max_sl_points, params.sl_buffer_points)
        ):
            pending = None
            continue
        signal = confirm_entry(
            pending,
            bar,
            target_points=params.target_points,
            sl_buffer=params.sl_buffer_points,
            use_stop_loss=params.use_stop_loss,
            max_sl_points=params.max_sl_points,
            require_reclaim=params.require_reclaim,
            min_confirm_body=params.min_confirm_body,
            require_close_break=params.require_close_break,
            one_shot_confirm=params.one_shot_confirm,
        )
        if signal is None:
            if pending.failed:
                pending = None
            continue
        if entry_log is not None:
            entry_log.append(signal)
        position = _open_position(signal, lots)
        pending = None
        position, fills, wallet = _manage_open(position, bar, wallet, params)
        trades.extend(fills)
        if position is not None and position.partial_taken:
            runners.append(position)
            position = None

    last = m1_rows[-1] if m1_rows else None
    open_left = ([position] if position is not None else []) + runners
    if last is not None:
        for leftover in open_left:
            reason = "end_of_data" if not leftover.partial_taken else "runner_end_of_data"
            trade, wallet = _close_trade(
                leftover, last["timestamp"], float(last["close"]), reason, wallet, params
            )
            trades.append(trade)
    result = _summarize(trades, params.starting_wallet_usd, grab_count, len(swings))
    available = usable_swings(swings, closed_ptr, params.swing_lookback, swept_ids)
    high = latest_swing(available, "high")
    low = latest_swing(available, "low")
    result.marked_high = high.price if high is not None else 0.0
    result.marked_low = low.price if low is not None else 0.0
    result.last_close = float(last["close"]) if last is not None else 0.0
    if pending is not None:
        result.pending_side = pending.side
        result.pending_swing = pending.swing.price
        result.pending_sweep = pending.sweep_extreme
        result.pending_grab_ts = pending.grab_ts
    return result
