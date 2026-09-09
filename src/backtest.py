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
from src.patterns import (
    PendingPattern,
    build_indicator_cache,
    confirm_pattern_entry,
    detect_pattern,
    pattern_config_from_params,
    pattern_invalidated,
)
from src.delta_data import RESOLUTION_SECONDS
from src.swings import (
    detect_swings,
    epoch_of,
    last_closed_bar_open,
    last_closed_m15_open,
    latest_swing,
    usable_swings,
)


@dataclass
class BacktestParams:
    target_points: float = 40.0
    position_lots: int = 500
    fee_pct_per_side: float = 0.05
    fee_maker_pct: float = 0.02
    maker_on_take_profit: bool = True
    maker_on_entry: bool = False
    scalper_offer: bool = True
    scalper_minutes: float = 30.0
    gst_pct: float = 0.0
    starting_wallet_usd: float = 10000.0
    usd_per_point_per_lot: float = 0.01
    swing_left: int = 2
    swing_right: int = 2
    swing_lookback: int = 48
    confirm_timeout_minutes: int = 120
    sl_buffer_points: float = 0.5
    use_stop_loss: bool = True
    max_sl_points: float = 25.0
    min_sweep_points: float = 3.0
    require_reclaim: bool = True
    require_close_back: bool = True
    grab_on_m15_close: bool = True
    min_confirm_body: float = 0.5
    require_close_break: bool = False
    one_shot_confirm: bool = False
    breakeven_points: float = 15.0
    # T1=30%, T2=40%, T3=10%, T4=10%, T5=all remaining
    exit_scale_pcts: tuple[float, ...] = (30.0, 40.0, 10.0, 10.0)
    partial_exit_pct: float = 30.0  # legacy alias (T1); prefer exit_scale_pcts
    max_targets: int = 5
    runner_target_points: float = 200.0
    trend_lookback: int = 6
    min_shadow_ratio: float = 2.5
    ema_period: int = 20
    rsi_period: int = 14
    rsi_oversold: float = 25.0
    rsi_overbought: float = 75.0
    min_pattern_points: float = 2.0
    volume_lookback: int = 10
    volume_spike_mult: float = 1.1
    require_volume_spike: bool = False
    require_rsi_extreme: bool = False
    require_ema_trend: bool = False
    require_swing_confluence: bool = False
    swing_confluence_points: float = 15.0
    min_rr_ratio: float = 1.5
    target_risk_multiple: float = 3.0
    use_adaptive_targets: bool = True
    require_double_confirm: bool = False
    # Gold production overlays (regime + entry + ATR risk + session)
    use_ema_regime: bool = True
    ema_fast: int = 20
    ema_slow: int = 50
    use_adx_filter: bool = True
    adx_period: int = 14
    adx_min: float = 20.0
    use_donchian_filter: bool = True
    donchian_period: int = 20
    use_bollinger_rsi: bool = True
    bb_period: int = 20
    bb_std: float = 2.0
    use_atr_stops: bool = True
    atr_period: int = 14
    atr_stop_mult: float = 1.5
    atr_target_mult: float = 2.0
    atr_max_risk_mult: float = 2.0
    use_session_filter: bool = True
    session_london_start: int = 7
    session_london_end: int = 10
    session_overlap_start: int = 12
    session_overlap_end: int = 16
    min_overlay_votes: int = 2

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
    original_lots: int = 0
    breakeven_done: bool = False
    partial_taken: bool = False
    targets_hit: int = 0
    target_step: float = 30.0

    def __post_init__(self) -> None:
        if self.original_stop == 0.0:
            self.original_stop = self.stop_loss
        if self.original_lots <= 0:
            self.original_lots = self.lots


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


def _is_take_profit_reason(reason: str) -> bool:
    return reason == "take_profit" or reason.startswith("take_profit_")


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
    contract_eth = params.usd_per_point_per_lot
    taker = params.fee_pct_per_side / 100.0
    maker = params.fee_maker_pct / 100.0
    entry_rate = maker if params.maker_on_entry else taker
    scalped = bool(
        params.scalper_offer and hold_minutes <= params.scalper_minutes
    )
    if scalped:
        exit_rate = 0.0
    elif params.maker_on_take_profit and _is_take_profit_reason(reason):
        exit_rate = maker
    else:
        exit_rate = taker
    gst = 1.0 + params.gst_pct / 100.0
    entry_notional_usd = abs(lots) * contract_eth * entry_price
    exit_notional_usd = abs(lots) * contract_eth * exit_price
    entry_fee = entry_notional_usd * entry_rate * gst
    exit_fee = exit_notional_usd * exit_rate * gst
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
    contract_eth = params.usd_per_point_per_lot
    notional_usd = abs(position.lots) * contract_eth * position.entry_price
    gross_usd = points * position.lots * contract_eth
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
    net = gross_usd - fee
    wallet += net
    risk_points = abs(position.entry_price - position.stop_loss)
    risk_usd = risk_points * position.lots * contract_eth
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
        "lot_usd": round(notional_usd, 2),
        "size_usd": round(notional_usd, 2),
        "risk_usd": round(risk_usd, 2),
        "points": round(points, 4),
        "gross_usd": round(gross_usd, 2),
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


def _target_price_at_level(position: OpenPosition, level: int, step: float) -> float:
    offset = step * level
    if position.side == "long":
        return position.entry_price + offset
    return position.entry_price - offset


def _stop_after_target_level(position: OpenPosition, level: int, step: float) -> float:
    """Trail SL after booking Tn.

    T1 → mid(entry, T1)
    T2 → T1
    T3 → T3  (so T4 phase SL = T3)
    T4 → T4  (so T5 phase SL = T4)
    """
    if level <= 0:
        return position.stop_loss
    if level == 1:
        entry = position.entry_price
        first_target = _target_price_at_level(position, 1, step)
        return (entry + first_target) / 2.0
    if level == 2:
        return _target_price_at_level(position, 1, step)
    # After T3+: SL locks at the target just hit (T4 uses T3, T5 uses T4)
    return _target_price_at_level(position, level, step)


def _exit_pcts(params: BacktestParams) -> tuple[float, ...]:
    raw = getattr(params, "exit_scale_pcts", None)
    if raw:
        return tuple(float(x) for x in raw)
    # Fallback: repeat legacy partial_exit_pct for early targets
    pct = float(params.partial_exit_pct or 30.0)
    return (pct, pct, pct, pct)


def _lots_for_target_level(
    original_lots: int,
    remaining_lots: int,
    level: int,
    max_targets: int,
    pcts: tuple[float, ...],
) -> int:
    """Close size at Tn as % of *original* lots; T_max closes all remaining."""
    if remaining_lots <= 0:
        return 0
    if level >= max_targets:
        return remaining_lots
    idx = level - 1
    if idx < 0 or idx >= len(pcts):
        return remaining_lots
    pct = pcts[idx]
    desired = int(round(original_lots * pct / 100.0))
    if desired < 1 and remaining_lots > 1:
        desired = 1
    # Keep at least 1 lot for later targets when possible
    levels_left_after = max_targets - level
    reserve = levels_left_after if remaining_lots > levels_left_after else 0
    max_close = remaining_lots - reserve if reserve > 0 else remaining_lots
    return max(0, min(desired, max_close, remaining_lots))


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
        original_lots=position.original_lots,
        breakeven_done=position.breakeven_done,
        partial_taken=position.partial_taken,
        targets_hit=position.targets_hit,
        target_step=position.target_step,
    )


def _manage_open(
    position: OpenPosition,
    bar: dict,
    wallet: float,
    params: BacktestParams,
) -> tuple[OpenPosition | None, list[dict], float]:
    maybe_move_to_breakeven(position, bar, params.breakeven_points)
    fills: list[dict] = []
    pcts = _exit_pcts(params)

    while True:
        exit_hit = check_bar_exit(position, bar)
        if exit_hit is None:
            return position, fills, wallet

        reason, exit_price = exit_hit
        if reason == "stop_loss":
            label = "stop_loss" if position.targets_hit == 0 else f"stop_loss_after_T{position.targets_hit}"
            trade, wallet = _close_trade(position, bar["timestamp"], exit_price, label, wallet, params)
            fills.append(trade)
            return None, fills, wallet

        level = position.targets_hit + 1
        if level >= params.max_targets:
            trade, wallet = _close_trade(
                position,
                bar["timestamp"],
                exit_price,
                f"take_profit_T{level}_final",
                wallet,
                params,
            )
            fills.append(trade)
            return None, fills, wallet

        closed = _lots_for_target_level(
            position.original_lots or position.lots,
            position.lots,
            level,
            params.max_targets,
            pcts,
        )
        if closed <= 0 or closed >= position.lots:
            # Not enough size to partial — close all at this target
            trade, wallet = _close_trade(
                position,
                bar["timestamp"],
                exit_price,
                f"take_profit_T{level}_final",
                wallet,
                params,
            )
            fills.append(trade)
            return None, fills, wallet

        slice_pos = _slice_position(position, closed)
        trade, wallet = _close_trade(
            slice_pos,
            bar["timestamp"],
            exit_price,
            f"take_profit_T{level}",
            wallet,
            params,
        )
        fills.append(trade)
        position.lots -= closed
        position.targets_hit = level
        position.partial_taken = True
        step = position.target_step
        position.stop_loss = _stop_after_target_level(position, level, step)
        position.target = _target_price_at_level(position, level + 1, step)

        if position.lots <= 0:
            return None, fills, wallet


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
    params: BacktestParams | None = None,
) -> BacktestResult:
    ending = trades[-1]["wallet"] if trades else starting_wallet
    gross_usd = sum(float(trade.get("gross_usd", 0.0)) for trade in trades)
    if params and params.position_lots > 0 and params.usd_per_point_per_lot > 0:
        net_points = gross_usd / (params.position_lots * params.usd_per_point_per_lot)
    else:
        net_points = sum(trade["points"] for trade in trades)
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
        net_points=round(net_points, 4),
        win_rate=round(len(wins) / len(trades), 4) if trades else 0.0,
        profit_factor=round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
        max_drawdown=round(max_dd, 2),
        trade_count=len(trades),
        wins=len(wins),
        losses=len(losses),
        tp_count=sum(1 for trade in trades if _is_take_profit_reason(str(trade["reason"]))),
        sl_count=sum(1 for trade in trades if trade["reason"] == "stop_loss"),
        total_fees=round(sum(trade["fee_usd"] for trade in trades), 2),
        avg_win_points=round(sum(win_points) / len(win_points), 4) if win_points else 0.0,
        avg_loss_points=round(sum(loss_points) / len(loss_points), 4) if loss_points else 0.0,
        grab_count=grab_count,
        swing_count=swing_count,
    )


def _open_position(signal: EntrySignal, lots: int) -> OpenPosition:
    target_step = abs(signal.target - signal.entry_price)
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
        target_step=target_step,
        original_lots=lots,
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
    result = _summarize(trades, params.starting_wallet_usd, grab_count, len(swings), params)
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


def _scan_new_patterns(
    signal_rows: list[dict],
    swings: list,
    start_index: int,
    end_index: int,
    params: BacktestParams,
    cache,
) -> tuple[PendingPattern | None, int]:
    cfg = pattern_config_from_params(params)
    found: PendingPattern | None = None
    count = 0
    for index in range(start_index, end_index + 1):
        if index < 0:
            continue
        pattern = detect_pattern(
            signal_rows[index],
            signal_rows,
            index,
            cfg=cfg,
            swings=swings,
            cache=cache,
        )
        if pattern is not None:
            found = pattern
            count += 1
    return found, count


def run_pattern_backtest(
    signal_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams | None = None,
    *,
    bar_seconds: int = 900,
    entry_log: list[EntrySignal] | None = None,
) -> BacktestResult:
    params = params or BacktestParams()
    cfg = pattern_config_from_params(params)
    cache = build_indicator_cache(signal_rows, cfg)
    swings = detect_swings(signal_rows, params.swing_left, params.swing_right)
    pending: PendingPattern | None = None
    position: OpenPosition | None = None
    runners: list[OpenPosition] = []
    trades: list[dict] = []
    wallet = params.starting_wallet_usd
    pattern_count = 0
    lots = params.position_lots
    signal_epochs = [epoch_of(row["timestamp"]) for row in signal_rows]
    closed_ptr = -1

    for bar in m1_rows:
        now = epoch_of(bar["timestamp"])
        prev_closed = closed_ptr
        closed_open = last_closed_bar_open(now, bar_seconds)
        while closed_ptr + 1 < len(signal_epochs) and signal_epochs[closed_ptr + 1] <= closed_open:
            closed_ptr += 1

        runners, runner_fills, wallet = _update_runners(runners, bar, wallet, params)
        trades.extend(runner_fills)

        if closed_ptr > prev_closed and position is None and pending is None and not runners:
            found, added = _scan_new_patterns(
                signal_rows, swings, prev_closed + 1, closed_ptr, params, cache
            )
            pattern_count += added
            if found is not None:
                found.pattern_epoch = signal_epochs[closed_ptr] + bar_seconds
                pending = found

        if position is not None:
            position, fills, wallet = _manage_open(position, bar, wallet, params)
            trades.extend(fills)
            if position is not None and position.partial_taken:
                runners.append(position)
                position = None
            continue

        if pending is None:
            continue
        if now < pending.pattern_epoch:
            continue

        age_minutes = (now - pending.pattern_epoch) / 60.0
        if age_minutes > params.confirm_timeout_minutes:
            pending = None
            continue
        if pattern_invalidated(pending, bar):
            pending = None
            continue

        signal = confirm_pattern_entry(pending, bar, cfg=cfg)
        if signal is None:
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

    result = _summarize(trades, params.starting_wallet_usd, pattern_count, len(swings), params)
    result.last_close = float(last["close"]) if last is not None else 0.0
    if pending is not None:
        result.pending_side = pending.side
        result.pending_swing = (
            pending.pattern_high if pending.side == "long" else pending.pattern_low
        )
        result.pending_sweep = (
            pending.pattern_low if pending.side == "long" else pending.pattern_high
        )
        result.pending_grab_ts = pending.pattern_ts
    return result


def bar_seconds_for_resolution(resolution: str) -> int:
    return RESOLUTION_SECONDS.get(resolution, 900)
