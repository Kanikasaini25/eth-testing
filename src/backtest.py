from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from src.rule_extractor import TradingRule

FIXED_ENTRY_LOTS = 100
PARTIAL_EXIT_LOTS = 80
RUNNER_LOTS = 20
ETH_PER_LOT = 0.01  # Delta ETHUSD: 1 lot = 0.01 ETH → 100 lots = 1 ETH


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    exit_reason: str
    side: str = ""
    trade_type: str = ""
    entry_lots: int = FIXED_ENTRY_LOTS
    lots: int = 0
    points: float = 0.0
    pnl_usd: float = 0.0
    wallet_balance: float = 0.0


def _trade_type_label(side: str) -> str:
    if side == "long":
        return "Buy"
    if side == "short":
        return "Sell"
    return ""


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
    backtest_mode: str = "daily"
    rule_compliance: dict[str, bool] | None = None


def _dates(rows: list[dict]) -> list[str]:
    return [row["timestamp"][:10] for row in rows]


def _run_long_backtest(
    rows: list[dict],
    entries: list[bool],
    exits: list[bool],
    stop_loss_pct: float | None = None,
    starting_wallet: float = 10_000,
) -> tuple[list[Trade], list[float]]:
    trades: list[Trade] = []
    equity = 1.0
    equity_curve = [equity]
    dates = _dates(rows)

    in_position = False
    entry_price = 0.0
    entry_date = ""

    for index, row in enumerate(rows):
        price = float(row["close"])
        low = float(row["low"])

        if in_position and stop_loss_pct is not None:
            stop_price = entry_price * (1 - stop_loss_pct / 100)
            if low <= stop_price:
                return_pct = ((stop_price - entry_price) / entry_price) * 100
                equity *= 1 + return_pct / 100
                trades.append(
                    Trade(
                        entry_date=entry_date,
                        exit_date=dates[index],
                        entry_price=round(entry_price, 2),
                        exit_price=round(stop_price, 2),
                        return_pct=round(return_pct, 2),
                        exit_reason="stop_loss",
                        side="long",
                        trade_type="Buy",
                        wallet_balance=round(starting_wallet * equity, 2),
                    )
                )
                in_position = False

        if not in_position and entries[index]:
            in_position = True
            entry_price = price
            entry_date = dates[index]
        elif in_position and exits[index]:
            return_pct = ((price - entry_price) / entry_price) * 100
            equity *= 1 + return_pct / 100
            trades.append(
                Trade(
                    entry_date=entry_date,
                    exit_date=dates[index],
                    entry_price=round(entry_price, 2),
                    exit_price=round(price, 2),
                    return_pct=round(return_pct, 2),
                    exit_reason="signal",
                    side="long",
                    trade_type="Buy",
                    wallet_balance=round(starting_wallet * equity, 2),
                )
            )
            in_position = False

        equity_curve.append(equity)

    if in_position:
        price = float(rows[-1]["close"])
        return_pct = ((price - entry_price) / entry_price) * 100
        equity *= 1 + return_pct / 100
        trades.append(
            Trade(
                entry_date=entry_date,
                exit_date=dates[-1],
                entry_price=round(entry_price, 2),
                exit_price=round(price, 2),
                return_pct=round(return_pct, 2),
                exit_reason="open_at_end",
                side="long",
                trade_type="Buy",
                wallet_balance=round(starting_wallet * equity, 2),
            )
        )

    return trades, equity_curve


def _swing_high_before(daily_rows: list[dict], day: str, lookback: int) -> float:
    highs: list[float] = []
    for row in daily_rows:
        if row["timestamp"][:10] >= day:
            break
        highs.append(float(row["high"]))
    if not highs:
        return 0.0
    window = highs[-lookback:] if len(highs) >= lookback else highs
    return max(window)


def _swing_low_before(daily_rows: list[dict], day: str, lookback: int) -> float:
    lows: list[float] = []
    for row in daily_rows:
        if row["timestamp"][:10] >= day:
            break
        lows.append(float(row["low"]))
    if not lows:
        return 0.0
    window = lows[-lookback:] if len(lows) >= lookback else lows
    return min(window)


def _daily_liquidity_levels(daily_rows: list[dict]) -> dict[str, dict[str, float]]:
    levels: dict[str, dict[str, float]] = {}
    for index in range(1, len(daily_rows)):
        day = daily_rows[index]["timestamp"][:10]
        previous = daily_rows[index - 1]
        levels[day] = {
            "upper": float(previous["high"]),
            "lower": float(previous["low"]),
        }
    return levels


def _return_pct(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return ((exit_price - entry_price) / entry_price) * 100
    return ((entry_price - exit_price) / entry_price) * 100


def _points_captured(side: str, entry_price: float, exit_price: float) -> float:
    if side == "long":
        return exit_price - entry_price
    return entry_price - exit_price


def _eth_size(lots: int) -> float:
    return lots * ETH_PER_LOT


def _gross_pnl_usd(points: float, lots: int) -> float:
    """$1 ETH price move × ETH size (100 lots = 1 ETH → ~$1 per point)."""
    return points * _eth_size(lots)


def _trading_fee_usd(price: float, lots: int, fee_pct_per_side: float) -> float:
    if fee_pct_per_side <= 0 or lots <= 0:
        return 0.0
    notional = price * _eth_size(lots)
    return notional * fee_pct_per_side / 100


def _record_trade(
    trades: list[Trade],
    entry_ts: str,
    exit_ts: str,
    entry_price: float,
    exit_price: float,
    reason: str,
    side: str,
    lots: int,
    wallet_balance: float,
    pnl_usd: float,
    entry_lots: int = FIXED_ENTRY_LOTS,
) -> None:
    return_pct = _return_pct(side, entry_price, exit_price)
    trades.append(
        Trade(
            entry_date=entry_ts[:16],
            exit_date=exit_ts[:16],
            entry_price=round(entry_price, 2),
            exit_price=round(exit_price, 2),
            return_pct=round(return_pct, 2),
            exit_reason=reason,
            side=side,
            trade_type=_trade_type_label(side),
            entry_lots=entry_lots,
            lots=lots,
            points=round(_points_captured(side, entry_price, exit_price), 2),
            pnl_usd=round(pnl_usd, 2),
            wallet_balance=round(wallet_balance, 2),
        )
    )


def _close_trade(
    trades: list[Trade],
    wallet_usd: float,
    entry_ts: str,
    exit_ts: str,
    entry_price: float,
    exit_price: float,
    reason: str,
    side: str,
    lots: int,
    position_lots: int,
    entry_fee_remaining: float,
    open_lots: int,
    fee_pct_per_side: float = 0.0,
) -> tuple[float, float, int]:
    points = _points_captured(side, entry_price, exit_price)
    gross = _gross_pnl_usd(points, lots)
    exit_fee = _trading_fee_usd(exit_price, lots, fee_pct_per_side)
    entry_fee_share = (
        entry_fee_remaining * (lots / open_lots) if open_lots else entry_fee_remaining
    )
    net_pnl = gross - exit_fee - entry_fee_share
    wallet_usd += net_pnl
    _record_trade(
        trades,
        entry_ts,
        exit_ts,
        entry_price,
        exit_price,
        reason,
        side,
        lots,
        wallet_usd,
        net_pnl,
        position_lots,
    )
    return wallet_usd, entry_fee_remaining - entry_fee_share, open_lots - lots


def _points_target(entry: float, side: str, points: float) -> float:
    if side == "long":
        return entry + points
    return entry - points


def _signal_body_ratio(open_price: float, high: float, low: float, close: float) -> float:
    candle_range = high - low
    if candle_range <= 0:
        return 0.0
    return abs(close - open_price) / candle_range


def _entry_win_rate(trades: list[Trade]) -> tuple[int, int, float]:
    groups: dict[tuple[str, float], list[Trade]] = {}
    for trade in trades:
        key = (trade.entry_date, trade.entry_price)
        groups.setdefault(key, []).append(trade)
    if not groups:
        return 0, 0, 0.0
    wins = sum(
        1
        for legs in groups.values()
        if sum(leg.pnl_usd for leg in legs) > 0
    )
    total = len(groups)
    return wins, total, (wins / total * 100)


def _liquidity_entry_valid(
    side: str,
    entry_price: float,
    stop_loss: float,
    reward_points: float,
    *,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    max_sl_pct: float,
) -> bool:
    sl_distance = abs(entry_price - stop_loss)
    if min_sl_points > 0 and sl_distance < min_sl_points:
        return False
    if max_sl_points > 0 and sl_distance > max_sl_points:
        return False
    if min_reward_to_risk > 0 and sl_distance > 0:
        if (reward_points / sl_distance) < min_reward_to_risk:
            return False
    sl_pct = (sl_distance / entry_price) * 100 if entry_price else 100.0
    if sl_pct > max_sl_pct:
        return False
    if side == "short" and stop_loss <= entry_price:
        return False
    if side == "long" and stop_loss >= entry_price:
        return False
    return True


def _in_utc_session(timestamp: str, start_hour: int, end_hour: int) -> bool:
    hour = int(timestamp[11:13])
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _previous_daily_candle(daily_rows: list[dict], day: str) -> dict | None:
    for index in range(1, len(daily_rows)):
        if daily_rows[index]["timestamp"][:10] == day:
            return daily_rows[index - 1]
    return None


def _daily_trend_allows(side: str, daily_rows: list[dict], day: str) -> bool:
    previous = _previous_daily_candle(daily_rows, day)
    if previous is None:
        return True
    prev_open = float(previous["open"])
    prev_close = float(previous["close"])
    if side == "short":
        return prev_close < prev_open
    return prev_close > prev_open


def _liquidity_sweep_at_upper(high: float, close: float, upper: float) -> bool:
    return high > upper and close < upper


def _liquidity_sweep_at_lower(low: float, close: float, lower: float) -> bool:
    return low < lower and close > lower


def _minutes_between(start_ts: str, end_ts: str) -> float:
    start = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
    end = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
    return max((end - start).total_seconds() / 60.0, 0.0)


def _near_liquidity_line(price: float, line: float, max_points: float) -> bool:
    if max_points <= 0:
        return True
    return abs(price - line) <= max_points


def _liquidity_timing_ok(
    first_touch_ts: str,
    signal_ts: str,
    max_minutes_after_touch: float,
) -> bool:
    if max_minutes_after_touch <= 0 or not first_touch_ts:
        return True
    return _minutes_between(first_touch_ts, signal_ts) <= max_minutes_after_touch


def _liquidity_targets(
    side: str,
    entry_price: float,
    daily_rows: list[dict],
    day: str,
    *,
    use_swing_target_for_partial: bool,
    partial_target_points: float,
    swing_lookback: int,
    runner_swing_lookback: int,
) -> tuple[float, float, float]:
    """Return (target_1 partial, target_2 runner, reward_points in price)."""
    if use_swing_target_for_partial:
        if side == "short":
            target_1 = _swing_low_before(daily_rows, day, swing_lookback)
            target_2 = _swing_low_before(daily_rows, day, runner_swing_lookback)
            if target_2 > 0 and target_1 > 0 and target_2 >= target_1:
                target_2 = target_1 - max(abs(entry_price - target_1) * 0.5, 1.0)
            reward = max(entry_price - target_1, 0.0) if target_1 > 0 else 0.0
        else:
            target_1 = _swing_high_before(daily_rows, day, swing_lookback)
            target_2 = _swing_high_before(daily_rows, day, runner_swing_lookback)
            if target_2 > 0 and target_1 > 0 and target_2 <= target_1:
                target_2 = target_1 + max(abs(target_1 - entry_price) * 0.5, 1.0)
            reward = max(target_1 - entry_price, 0.0) if target_1 > 0 else 0.0
        return target_1, target_2, reward

    target_1 = _points_target(entry_price, side, partial_target_points)
    if side == "short":
        target_2 = _swing_low_before(daily_rows, day, swing_lookback)
    else:
        target_2 = _swing_high_before(daily_rows, day, swing_lookback)
    return target_1, target_2, partial_target_points


def _passes_liquidity_entry_filters(
    *,
    side: str,
    timestamp: str,
    entry_price: float,
    stop_loss: float,
    reward_points: float,
    daily_rows: list[dict],
    day: str,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    max_sl_pct: float,
    require_liquidity_sweep: bool = False,
    signal_high: float = 0.0,
    signal_low: float = 0.0,
    signal_close: float = 0.0,
    upper: float = 0.0,
    lower: float = 0.0,
    use_daily_trend_filter: bool = False,
    use_session_filter: bool = False,
    session_start_hour_utc: int = 8,
    session_end_hour_utc: int = 20,
    require_signal_touches_line: bool = False,
    max_entry_distance_points: float = 0.0,
    max_minutes_after_touch: float = 0.0,
    first_touch_ts: str = "",
) -> bool:
    if not _liquidity_entry_valid(
        side,
        entry_price,
        stop_loss,
        reward_points,
        min_sl_points=min_sl_points,
        max_sl_points=max_sl_points,
        min_reward_to_risk=min_reward_to_risk,
        max_sl_pct=max_sl_pct,
    ):
        return False
    if use_session_filter and not _in_utc_session(
        timestamp, session_start_hour_utc, session_end_hour_utc
    ):
        return False
    if use_daily_trend_filter and not _daily_trend_allows(side, daily_rows, day):
        return False
    if require_liquidity_sweep:
        if side == "short" and not _liquidity_sweep_at_upper(signal_high, signal_close, upper):
            return False
        if side == "long" and not _liquidity_sweep_at_lower(signal_low, signal_close, lower):
            return False
    return _passes_liquidity_proximity_filters(
        side=side,
        entry_price=entry_price,
        timestamp=timestamp,
        signal_high=signal_high,
        signal_low=signal_low,
        upper=upper,
        lower=lower,
        first_touch_ts=first_touch_ts,
        require_signal_touches_line=require_signal_touches_line,
        max_entry_distance_points=max_entry_distance_points,
        max_minutes_after_touch=max_minutes_after_touch,
    )


def _passes_liquidity_proximity_filters(
    *,
    side: str,
    entry_price: float,
    timestamp: str,
    signal_high: float,
    signal_low: float,
    upper: float,
    lower: float,
    first_touch_ts: str,
    require_signal_touches_line: bool,
    max_entry_distance_points: float,
    max_minutes_after_touch: float,
) -> bool:
    line_price = upper if side == "short" else lower
    signal_touches = signal_high >= upper if side == "short" else signal_low <= lower
    if require_signal_touches_line and not signal_touches:
        return False
    if not _near_liquidity_line(entry_price, line_price, max_entry_distance_points):
        return False
    return _liquidity_timing_ok(first_touch_ts, timestamp, max_minutes_after_touch)


def _bar_prices_sane(row: dict, ref_price: float, max_deviation_pct: float = 15.0) -> bool:
    low = float(row["low"])
    high = float(row["high"])
    close = float(row["close"])
    if low <= 0 or high <= 0 or close <= 0 or low > high:
        return False
    if ref_price <= 0:
        return True
    limit = max_deviation_pct / 100
    return low >= ref_price * (1 - limit) and high <= ref_price * (1 + limit)


def _effective_low(row: dict, ref_price: float) -> float:
    if _bar_prices_sane(row, ref_price):
        return float(row["low"])
    return float(row["close"])


def _effective_high(row: dict, ref_price: float) -> float:
    if _bar_prices_sane(row, ref_price):
        return float(row["high"])
    return float(row["close"])


def backtest_liquidity_intraday(
    intraday_rows: list[dict],
    daily_rows: list[dict],
    rule: TradingRule,
) -> BacktestResult:
    """LQDTY on ETH futures: 100 lots entry, partial at +10 points, runner to swing."""
    levels = _daily_liquidity_levels(daily_rows)
    swing_lookback = int(rule.parameters.get("swing_lookback_days", 20))
    max_trades = int(rule.parameters.get("max_trades_per_sequence", 3))
    max_full_sl = int(rule.parameters.get("max_full_stop_losses_per_session", 2))
    max_sl_pct = float(rule.parameters.get("max_stop_loss_pct", 5.0))
    position_lots = int(rule.parameters.get("position_lots", FIXED_ENTRY_LOTS))
    partial_exit_lots = int(
        rule.parameters.get("partial_exit_lots", position_lots * PARTIAL_EXIT_LOTS // FIXED_ENTRY_LOTS)
    )
    runner_lots = int(
        rule.parameters.get("runner_lots", position_lots - partial_exit_lots)
    )
    partial_target_points = float(rule.parameters.get("partial_target_points", 10))
    use_swing_target_for_partial = bool(rule.parameters.get("use_swing_target_for_partial", False))
    runner_swing_lookback = int(rule.parameters.get("runner_swing_lookback_days", 60))
    max_entries_per_line = int(rule.parameters.get("max_entries_per_liquidity_line_per_day", 1))
    min_sl_points = float(rule.parameters.get("min_stop_loss_points", 4.0))
    max_sl_points = float(rule.parameters.get("max_stop_loss_points", 7.0))
    min_reward_to_risk = float(rule.parameters.get("min_reward_to_risk", 2.5))
    min_signal_body_ratio = float(rule.parameters.get("min_signal_body_ratio", 0.75))
    min_signal_range_points = float(rule.parameters.get("min_signal_range_points", 3.5))
    entry_on_next_candle = bool(rule.parameters.get("entry_on_next_candle", True))
    require_close_beyond_signal = bool(rule.parameters.get("require_close_beyond_signal", True))
    require_liquidity_sweep = bool(rule.parameters.get("require_liquidity_sweep", False))
    require_signal_touches_line = bool(rule.parameters.get("require_signal_touches_line", False))
    max_entry_distance_points = float(rule.parameters.get("max_entry_distance_from_line_points", 8.0))
    max_minutes_after_touch = float(rule.parameters.get("max_minutes_after_liquidity_touch", 0.0))
    allow_longs = bool(rule.parameters.get("allow_longs", True))
    allow_shorts = bool(rule.parameters.get("allow_shorts", True))
    use_daily_trend_filter = bool(rule.parameters.get("use_daily_trend_filter", False))
    use_session_filter = bool(rule.parameters.get("use_session_filter", True))
    session_start_hour_utc = int(rule.parameters.get("session_start_hour_utc", 8))
    session_end_hour_utc = int(rule.parameters.get("session_end_hour_utc", 20))
    fee_pct_per_side = float(rule.parameters.get("fee_pct_per_side", 0.05))
    partial_exit_reason = (
        "partial_swing_target"
        if use_swing_target_for_partial
        else f"partial_target_{int(partial_target_points)}pts"
    )
    trailing_stop_points = float(rule.parameters.get("trailing_stop_points", 3.0))
    use_trailing_after_partial = bool(rule.parameters.get("use_trailing_stop_after_partial", True))
    starting_wallet = float(rule.parameters.get("starting_wallet_usd", 10_000))

    trades: list[Trade] = []
    wallet_usd = starting_wallet
    equity_curve = [wallet_usd / starting_wallet]

    in_position = False
    side = ""
    entry_price = 0.0
    stop_loss = 0.0
    target_1 = 0.0
    target_2 = 0.0
    entry_ts = ""
    partial_taken = False
    runner_open = False
    best_price = 0.0
    entry_fee_remaining = 0.0
    open_lots = 0

    current_day = ""
    touched_upper = False
    touched_lower = False
    first_upper_ts = ""
    first_lower_ts = ""
    pending_red: dict[str, float] | None = None
    pending_green: dict[str, float] | None = None
    trades_in_sequence = 0
    full_sl_count = 0
    upper_entries_today = 0
    lower_entries_today = 0
    upper_line_blocked = False
    lower_line_blocked = False
    entry_line = ""

    for index, row in enumerate(intraday_rows):
        prev_row = intraday_rows[index - 1] if index > 0 else None
        timestamp = row["timestamp"]
        day = timestamp[:10]
        open_price = float(row["open"])
        close = float(row["close"])
        bar_ref = entry_price if in_position else close
        high = _effective_high(row, bar_ref)
        low = _effective_low(row, bar_ref)

        if day != current_day:
            current_day = day
            touched_upper = False
            touched_lower = False
            first_upper_ts = ""
            first_lower_ts = ""
            pending_red = None
            pending_green = None
            trades_in_sequence = 0
            full_sl_count = 0
            upper_entries_today = 0
            lower_entries_today = 0
            upper_line_blocked = False
            lower_line_blocked = False

        if day not in levels:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        upper = levels[day]["upper"]
        lower = levels[day]["lower"]

        if in_position:
            if side == "long":
                if partial_taken and runner_open and use_trailing_after_partial:
                    best_price = max(best_price, high)
                    stop_loss = max(entry_price, best_price - trailing_stop_points)

                if not partial_taken and high >= target_1:
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_1,
                        partial_exit_reason,
                        "long",
                        partial_exit_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    partial_taken = True
                    runner_open = True
                    best_price = max(target_1, high)
                    stop_loss = (
                        max(entry_price, best_price - trailing_stop_points)
                        if use_trailing_after_partial
                        else entry_price
                    )
                elif partial_taken and runner_open and high >= target_2:
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_2,
                        "runner_swing_target",
                        "long",
                        runner_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    in_position = False
                    runner_open = False
                elif low <= stop_loss:
                    if partial_taken and use_trailing_after_partial and stop_loss > entry_price:
                        reason = "trailing_stop"
                    elif partial_taken and stop_loss == entry_price:
                        reason = "breakeven_stop"
                    else:
                        reason = "stop_loss"
                    exit_lots = runner_lots if partial_taken else position_lots
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        stop_loss,
                        reason,
                        "long",
                        exit_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    in_position = False
                    runner_open = False
                    if not partial_taken:
                        full_sl_count += 1
                        if entry_line == "upper":
                            upper_line_blocked = True
                        elif entry_line == "lower":
                            lower_line_blocked = True

            elif side == "short":
                if partial_taken and runner_open and use_trailing_after_partial:
                    best_price = min(best_price, low) if best_price > 0 else low
                    stop_loss = min(entry_price, best_price + trailing_stop_points)

                if not partial_taken and low <= target_1:
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_1,
                        partial_exit_reason,
                        "short",
                        partial_exit_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    partial_taken = True
                    runner_open = True
                    best_price = min(target_1, low)
                    stop_loss = (
                        min(entry_price, best_price + trailing_stop_points)
                        if use_trailing_after_partial
                        else entry_price
                    )
                elif partial_taken and runner_open and low <= target_2:
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_2,
                        "runner_swing_target",
                        "short",
                        runner_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    in_position = False
                    runner_open = False
                elif high >= stop_loss:
                    if partial_taken and use_trailing_after_partial and stop_loss < entry_price:
                        reason = "trailing_stop"
                    elif partial_taken and stop_loss == entry_price:
                        reason = "breakeven_stop"
                    else:
                        reason = "stop_loss"
                    exit_lots = runner_lots if partial_taken else position_lots
                    wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                        trades,
                        wallet_usd,
                        entry_ts,
                        timestamp,
                        entry_price,
                        stop_loss,
                        reason,
                        "short",
                        exit_lots,
                        position_lots,
                        entry_fee_remaining,
                        open_lots,
                        fee_pct_per_side=fee_pct_per_side,
                    )
                    in_position = False
                    runner_open = False
                    if not partial_taken:
                        full_sl_count += 1
                        if entry_line == "upper":
                            upper_line_blocked = True
                        elif entry_line == "lower":
                            lower_line_blocked = True

            equity_curve.append(wallet_usd / starting_wallet)
            continue

        if full_sl_count >= max_full_sl or trades_in_sequence >= max_trades:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        if high >= upper:
            touched_upper = True
            if not first_upper_ts:
                first_upper_ts = timestamp
        if low <= lower:
            touched_lower = True
            if not first_lower_ts:
                first_lower_ts = timestamp

        if not touched_upper and not touched_lower:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        if touched_upper and close < open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            candle_range = high - low
            sweep_ok = not require_liquidity_sweep or _liquidity_sweep_at_upper(high, close, upper)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or candle_range >= min_signal_range_points
            touches_line = high >= upper
            timing_ok = _liquidity_timing_ok(first_upper_ts, timestamp, max_minutes_after_touch)
            if body_ok and range_ok and sweep_ok and timing_ok:
                if not require_signal_touches_line or touches_line:
                    pending_red = {
                        "high": high,
                        "low": low,
                        "close": close,
                        "index": index,
                    }

        if touched_lower and close > open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            candle_range = high - low
            sweep_ok = not require_liquidity_sweep or _liquidity_sweep_at_lower(low, close, lower)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or candle_range >= min_signal_range_points
            touches_line = low <= lower
            timing_ok = _liquidity_timing_ok(first_lower_ts, timestamp, max_minutes_after_touch)
            if body_ok and range_ok and sweep_ok and timing_ok:
                if not require_signal_touches_line or touches_line:
                    pending_green = {
                        "high": high,
                        "low": low,
                        "close": close,
                        "index": index,
                    }

        can_enter_short = allow_shorts and pending_red and (
            index > pending_red["index"] if entry_on_next_candle else True
        )
        if can_enter_short and low < pending_red["low"]:
            short_break_ok = (
                close < pending_red["low"] if require_close_beyond_signal else True
            )
            if short_break_ok:
                if upper_line_blocked or upper_entries_today >= max_entries_per_line:
                    pending_red = None
                    equity_curve.append(wallet_usd / starting_wallet)
                    continue
                entry_price = close if require_close_beyond_signal else pending_red["low"]
                stop_loss = float(prev_row["high"]) if prev_row else pending_red["high"]
                target_1, target_2, reward_points = _liquidity_targets(
                    "short",
                    entry_price,
                    daily_rows,
                    day,
                    use_swing_target_for_partial=use_swing_target_for_partial,
                    partial_target_points=partial_target_points,
                    swing_lookback=swing_lookback,
                    runner_swing_lookback=runner_swing_lookback,
                )
                signal = pending_red
                if (
                    _passes_liquidity_entry_filters(
                        side="short",
                        timestamp=timestamp,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        reward_points=reward_points,
                        daily_rows=daily_rows,
                        day=day,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                        max_sl_pct=max_sl_pct,
                        require_liquidity_sweep=require_liquidity_sweep,
                        signal_high=signal["high"],
                        signal_low=signal["low"],
                        signal_close=signal["close"],
                        upper=upper,
                        lower=lower,
                        use_daily_trend_filter=use_daily_trend_filter,
                        use_session_filter=use_session_filter,
                        session_start_hour_utc=session_start_hour_utc,
                        session_end_hour_utc=session_end_hour_utc,
                        require_signal_touches_line=require_signal_touches_line,
                        max_entry_distance_points=max_entry_distance_points,
                        max_minutes_after_touch=max_minutes_after_touch,
                        first_touch_ts=first_upper_ts,
                    )
                    and target_1 > 0
                    and entry_price > target_1
                ):
                    in_position = True
                    side = "short"
                    entry_line = "upper"
                    entry_ts = timestamp
                    partial_taken = False
                    runner_open = False
                    open_lots = position_lots
                    entry_fee_remaining = _trading_fee_usd(
                        entry_price, position_lots, fee_pct_per_side
                    )
                    trades_in_sequence += 1
                    upper_entries_today += 1
                    pending_red = None

        can_enter_long = allow_longs and pending_green and (
            index > pending_green["index"] if entry_on_next_candle else True
        )
        if can_enter_long and high > pending_green["high"]:
            long_break_ok = (
                close > pending_green["high"] if require_close_beyond_signal else True
            )
            if long_break_ok:
                if lower_line_blocked or lower_entries_today >= max_entries_per_line:
                    pending_green = None
                    equity_curve.append(wallet_usd / starting_wallet)
                    continue
                entry_price = close if require_close_beyond_signal else pending_green["high"]
                stop_loss = float(prev_row["low"]) if prev_row else pending_green["low"]
                target_1, target_2, reward_points = _liquidity_targets(
                    "long",
                    entry_price,
                    daily_rows,
                    day,
                    use_swing_target_for_partial=use_swing_target_for_partial,
                    partial_target_points=partial_target_points,
                    swing_lookback=swing_lookback,
                    runner_swing_lookback=runner_swing_lookback,
                )
                signal = pending_green
                if (
                    _passes_liquidity_entry_filters(
                        side="long",
                        timestamp=timestamp,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        reward_points=reward_points,
                        daily_rows=daily_rows,
                        day=day,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                        max_sl_pct=max_sl_pct,
                        require_liquidity_sweep=require_liquidity_sweep,
                        signal_high=signal["high"],
                        signal_low=signal["low"],
                        signal_close=signal["close"],
                        upper=upper,
                        lower=lower,
                        use_daily_trend_filter=use_daily_trend_filter,
                        use_session_filter=use_session_filter,
                        session_start_hour_utc=session_start_hour_utc,
                        session_end_hour_utc=session_end_hour_utc,
                        require_signal_touches_line=require_signal_touches_line,
                        max_entry_distance_points=max_entry_distance_points,
                        max_minutes_after_touch=max_minutes_after_touch,
                        first_touch_ts=first_lower_ts,
                    )
                    and target_1 > 0
                    and entry_price < target_1
                ):
                    in_position = True
                    side = "long"
                    entry_line = "lower"
                    entry_ts = timestamp
                    partial_taken = False
                    runner_open = False
                    open_lots = position_lots
                    entry_fee_remaining = _trading_fee_usd(
                        entry_price, position_lots, fee_pct_per_side
                    )
                    trades_in_sequence += 1
                    lower_entries_today += 1
                    pending_green = None

        equity_curve.append(wallet_usd / starting_wallet)

    if in_position:
        last = intraday_rows[-1]
        exit_price = float(last["close"])
        exit_lots = runner_lots if partial_taken else position_lots
        wallet_usd, entry_fee_remaining, open_lots = _close_trade(
            trades,
            wallet_usd,
            entry_ts,
            last["timestamp"],
            entry_price,
            exit_price,
            "open_at_end",
            side,
            exit_lots,
            position_lots,
            entry_fee_remaining,
            open_lots,
            fee_pct_per_side=fee_pct_per_side,
        )

    compliance = {
        "uses_previous_day_high_low_lines": True,
        "uses_1m_candle_confirmation": True,
        "supports_long_and_short": True,
        "uses_previous_candle_wick_stop_loss": True,
        "entry_on_next_candle": entry_on_next_candle,
        "requires_close_beyond_signal": require_close_beyond_signal,
        "filters_min_stop_loss_points": min_sl_points >= 3.0,
        "filters_max_stop_loss_points": max_sl_points <= 7.0,
        "fixed_100_lot_entry": position_lots == 100,
        "uses_swing_target_for_partial": use_swing_target_for_partial,
        "uses_fixed_point_partial_target": not use_swing_target_for_partial,
        "keeps_runner_after_partial": True,
        "uses_trailing_stop_on_runner": use_trailing_after_partial,
        "moves_stop_to_breakeven_after_partial": not use_trailing_after_partial,
        "uses_swing_target_for_runner": True,
        "limits_max_trades_per_session": True,
        "limits_max_full_stop_losses": True,
        "one_attempt_per_liquidity_line_per_day": max_entries_per_line == 1,
        "blocks_line_after_full_stop_loss": True,
        "skips_middle_zone_without_touch": True,
        "instrument_eth_futures": True,
        "requires_liquidity_sweep_rejection": require_liquidity_sweep,
        "requires_signal_candle_at_line": require_signal_touches_line,
        "filters_entry_distance_from_line": max_entry_distance_points > 0,
        "filters_minutes_after_liquidity_touch": max_minutes_after_touch > 0,
        "allows_longs": allow_longs,
        "allows_shorts": allow_shorts,
        "uses_daily_trend_filter": use_daily_trend_filter,
        "uses_utc_session_filter": use_session_filter,
        "simulates_trading_fees": fee_pct_per_side > 0,
    }

    result = _build_result(rule, trades, equity_curve, daily_rows, entry_based_win_rate=True)
    result.backtest_mode = (
        "eth_100lots_swing" if use_swing_target_for_partial else "eth_100lots_filtered_entries"
    )
    result.rule_compliance = compliance
    return result


def backtest_liquidity(rows: list[dict], rule: TradingRule) -> BacktestResult:
    """Daily fallback when 1m data is not supplied."""
    entries = [False] * len(rows)
    exits = [False] * len(rows)

    for index in range(2, len(rows)):
        setup = rows[index - 2]
        signal = rows[index - 1]
        current = rows[index]

        upper = float(setup["high"])
        lower = float(setup["low"])
        signal_open = float(signal["open"])
        signal_close = float(signal["close"])
        signal_high = float(signal["high"])
        signal_low = float(signal["low"])
        current_high = float(current["high"])
        current_low = float(current["low"])

        touched_lower = float(signal["low"]) <= lower
        touched_upper = float(signal["high"]) >= upper

        long_signal = touched_lower and signal_close > signal_open and current_high > signal_high
        short_signal = touched_upper and signal_close < signal_open and current_low < signal_low

        entries[index] = long_signal
        exits[index] = short_signal or current_low < signal_low

    trades, equity = _run_long_backtest(rows, entries, exits)
    result = _build_result(rule, trades, equity, rows)
    result.backtest_mode = "daily_approximation"
    result.rule_compliance = {
        "uses_previous_day_high_low_lines": True,
        "uses_1m_candle_confirmation": False,
        "supports_long_and_short": False,
        "uses_signal_candle_stop_loss": False,
        "uses_swing_target": False,
        "limits_max_trades_per_session": False,
        "limits_max_full_stop_losses": False,
        "skips_middle_zone_without_touch": True,
    }
    return result


def backtest_rule(
    rows: list[dict],
    rule: TradingRule,
    intraday_rows: list[dict] | None = None,
    daily_rows: list[dict] | None = None,
) -> BacktestResult:
    if rule.strategy_type != "liquidity":
        raise ValueError(f"Unsupported strategy type: {rule.strategy_type}")
    if intraday_rows and daily_rows:
        return backtest_liquidity_intraday(intraday_rows, daily_rows, rule)
    return backtest_liquidity(rows, rule)


def _build_result(
    rule: TradingRule,
    trades: list[Trade],
    equity: list[float],
    rows: list[dict],
    entry_based_win_rate: bool = False,
) -> BacktestResult:
    total_trades = len(trades)
    if entry_based_win_rate and trades:
        wins, entry_count, win_rate = _entry_win_rate(trades)
        total_trades = entry_count
    else:
        wins = sum(1 for trade in trades if trade.return_pct > 0)
        win_rate = (wins / total_trades * 100) if total_trades else 0.0
    avg_return = (
        sum(trade.return_pct for trade in trades) / total_trades if total_trades else 0.0
    )

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

    return BacktestResult(
        rule_name=rule.name,
        strategy_type=rule.strategy_type,
        total_trades=total_trades,
        win_rate=round(win_rate, 2),
        total_return_pct=round(total_return, 2),
        buy_hold_return_pct=round(buy_hold, 2),
        max_drawdown_pct=round(max_drawdown, 2),
        avg_return_pct=round(avg_return, 2),
        verdict=verdict,
        trades=trades,
    )


def result_to_dict(result: BacktestResult) -> dict:
    return asdict(result)
