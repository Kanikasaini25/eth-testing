from __future__ import annotations

from dataclasses import asdict, dataclass

from src.rule_extractor import TradingRule

FIXED_ENTRY_LOTS = 100
PARTIAL_EXIT_LOTS = 80
RUNNER_LOTS = 20


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


def _closes(rows: list[dict]) -> list[float]:
    return [float(row["close"]) for row in rows]


def _lows(rows: list[dict]) -> list[float]:
    return [float(row["low"]) for row in rows]


def _dates(rows: list[dict]) -> list[str]:
    return [row["timestamp"][:10] for row in rows]


def compute_sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        result[index] = sum(values[index - period + 1 : index + 1]) / period
    return result


def compute_ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result

    multiplier = 2 / (period + 1)
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    previous = seed

    for index in range(period, len(values)):
        current = (values[index] - previous) * multiplier + previous
        result[index] = current
        previous = current

    return result


def compute_macd(
    values: list[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[list[float | None], list[float | None]]:
    ema_fast = compute_ema(values, fast)
    ema_slow = compute_ema(values, slow)
    macd_line: list[float | None] = [None] * len(values)
    macd_points: list[float] = []

    for index, (fast_value, slow_value) in enumerate(zip(ema_fast, ema_slow)):
        if fast_value is None or slow_value is None:
            continue
        value = fast_value - slow_value
        macd_line[index] = value
        macd_points.append(value)

    signal_line: list[float | None] = [None] * len(values)
    if len(macd_points) >= signal:
        signal_values = compute_ema(macd_points, signal)
        macd_index = 0
        for index in range(len(values)):
            if macd_line[index] is None:
                continue
            signal_line[index] = signal_values[macd_index]
            macd_index += 1

    return macd_line, signal_line


def _crosses_series_above(
    previous: float | None,
    current: float | None,
    previous_ref: float | None,
    current_ref: float | None,
) -> bool:
    return (
        previous is not None
        and current is not None
        and previous_ref is not None
        and current_ref is not None
        and previous <= previous_ref
        and current > current_ref
    )


def _crosses_series_below(
    previous: float | None,
    current: float | None,
    previous_ref: float | None,
    current_ref: float | None,
) -> bool:
    return (
        previous is not None
        and current is not None
        and previous_ref is not None
        and current_ref is not None
        and previous >= previous_ref
        and current < current_ref
    )


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


def backtest_ma_crossover(rows: list[dict], rule: TradingRule) -> BacktestResult:
    fast = int(rule.parameters.get("fast_period", 50))
    slow = int(rule.parameters.get("slow_period", 200))

    closes = _closes(rows)
    fast_ma = compute_sma(closes, fast)
    slow_ma = compute_sma(closes, slow)
    entries = [False] * len(rows)
    exits = [False] * len(rows)

    for index in range(1, len(rows)):
        entries[index] = _crosses_series_above(
            fast_ma[index - 1], fast_ma[index], slow_ma[index - 1], slow_ma[index]
        )
        exits[index] = _crosses_series_below(
            fast_ma[index - 1], fast_ma[index], slow_ma[index - 1], slow_ma[index]
        )

    trades, equity = _run_long_backtest(rows, entries, exits)
    return _build_result(rule, trades, equity, rows)


def backtest_macd(rows: list[dict], rule: TradingRule) -> BacktestResult:
    fast = int(rule.parameters.get("fast", 12))
    slow = int(rule.parameters.get("slow", 26))
    signal = int(rule.parameters.get("signal", 9))

    closes = _closes(rows)
    macd_line, signal_line = compute_macd(closes, fast, slow, signal)
    entries = [False] * len(rows)
    exits = [False] * len(rows)

    for index in range(1, len(rows)):
        entries[index] = _crosses_series_above(
            macd_line[index - 1], macd_line[index], signal_line[index - 1], signal_line[index]
        )
        exits[index] = _crosses_series_below(
            macd_line[index - 1], macd_line[index], signal_line[index - 1], signal_line[index]
        )

    trades, equity = _run_long_backtest(rows, entries, exits)
    return _build_result(rule, trades, equity, rows)


def backtest_breakout(rows: list[dict], rule: TradingRule) -> BacktestResult:
    lookback = int(rule.parameters.get("lookback", 20))
    highs = [float(row["high"]) for row in rows]
    closes = _closes(rows)
    entries = [False] * len(rows)
    exits = [False] * len(rows)
    entry_level: float | None = None

    for index in range(lookback, len(rows)):
        resistance = max(highs[index - lookback : index])
        if closes[index] > resistance:
            entries[index] = True
            entry_level = closes[index]
        elif entry_level is not None and closes[index] < entry_level:
            exits[index] = True
            entry_level = None

    trades, equity = _run_long_backtest(rows, entries, exits)
    return _build_result(rule, trades, equity, rows)


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
    entry_lots: int = FIXED_ENTRY_LOTS,
) -> float:
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
            wallet_balance=round(wallet_balance, 2),
        )
    )
    return return_pct


def _apply_return(equity: float, return_pct: float, weight: float = 1.0) -> float:
    return equity * (1 + (return_pct * weight) / 100)


def _close_trade(
    trades: list[Trade],
    equity: float,
    entry_ts: str,
    exit_ts: str,
    entry_price: float,
    exit_price: float,
    reason: str,
    side: str,
    lots: int,
    position_lots: int,
    starting_wallet: float,
) -> float:
    return_pct = _return_pct(side, entry_price, exit_price)
    weight = lots / position_lots if position_lots else 1.0
    equity = _apply_return(equity, return_pct, weight)
    _record_trade(
        trades,
        entry_ts,
        exit_ts,
        entry_price,
        exit_price,
        reason,
        side,
        lots,
        starting_wallet * equity,
        position_lots,
    )
    return equity


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
        if sum(leg.points * leg.lots for leg in legs) > 0
    )
    total = len(groups)
    return wins, total, (wins / total * 100)


def _liquidity_entry_valid(
    side: str,
    entry_price: float,
    stop_loss: float,
    partial_target_points: float,
    *,
    min_sl_points: float,
    max_sl_points: float,
    min_reward_to_risk: float,
    max_sl_pct: float,
) -> bool:
    sl_distance = abs(entry_price - stop_loss)
    if sl_distance < min_sl_points or sl_distance > max_sl_points:
        return False
    if (partial_target_points / sl_distance) < min_reward_to_risk:
        return False
    sl_pct = (sl_distance / entry_price) * 100 if entry_price else 100.0
    if sl_pct > max_sl_pct:
        return False
    if side == "short" and stop_loss <= entry_price:
        return False
    if side == "long" and stop_loss >= entry_price:
        return False
    return True


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
    position_lots = FIXED_ENTRY_LOTS
    partial_exit_lots = PARTIAL_EXIT_LOTS
    runner_lots = RUNNER_LOTS
    partial_target_points = float(rule.parameters.get("partial_target_points", 5))
    max_entries_per_line = int(rule.parameters.get("max_entries_per_liquidity_line_per_day", 1))
    min_sl_points = float(rule.parameters.get("min_stop_loss_points", 3.0))
    max_sl_points = float(rule.parameters.get("max_stop_loss_points", 7.0))
    min_reward_to_risk = float(rule.parameters.get("min_reward_to_risk", 2.0))
    min_signal_body_ratio = float(rule.parameters.get("min_signal_body_ratio", 0.45))
    min_signal_range_points = float(rule.parameters.get("min_signal_range_points", 2.0))
    entry_on_next_candle = bool(rule.parameters.get("entry_on_next_candle", True))
    require_close_beyond_signal = bool(rule.parameters.get("require_close_beyond_signal", True))
    partial_exit_reason = f"partial_target_{int(partial_target_points)}pts"
    trailing_stop_points = float(rule.parameters.get("trailing_stop_points", 3.0))
    use_trailing_after_partial = bool(rule.parameters.get("use_trailing_stop_after_partial", True))
    starting_wallet = float(rule.parameters.get("starting_wallet_usd", 10_000))

    trades: list[Trade] = []
    equity = 1.0
    equity_curve = [equity]

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

    current_day = ""
    touched_upper = False
    touched_lower = False
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
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if day != current_day:
            current_day = day
            touched_upper = False
            touched_lower = False
            pending_red = None
            pending_green = None
            trades_in_sequence = 0
            full_sl_count = 0
            upper_entries_today = 0
            lower_entries_today = 0
            upper_line_blocked = False
            lower_line_blocked = False

        if day not in levels:
            equity_curve.append(equity)
            continue

        upper = levels[day]["upper"]
        lower = levels[day]["lower"]

        if in_position:
            if side == "long":
                if partial_taken and runner_open and use_trailing_after_partial:
                    best_price = max(best_price, high)
                    stop_loss = max(entry_price, best_price - trailing_stop_points)

                if not partial_taken and high >= target_1:
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_1,
                        partial_exit_reason,
                        "long",
                        partial_exit_lots,
                        position_lots,
                        starting_wallet,
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
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_2,
                        "runner_swing_target",
                        "long",
                        runner_lots,
                        position_lots,
                        starting_wallet,
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
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        stop_loss,
                        reason,
                        "long",
                        exit_lots,
                        position_lots,
                        starting_wallet,
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
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_1,
                        partial_exit_reason,
                        "short",
                        partial_exit_lots,
                        position_lots,
                        starting_wallet,
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
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        target_2,
                        "runner_swing_target",
                        "short",
                        runner_lots,
                        position_lots,
                        starting_wallet,
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
                    equity = _close_trade(
                        trades,
                        equity,
                        entry_ts,
                        timestamp,
                        entry_price,
                        stop_loss,
                        reason,
                        "short",
                        exit_lots,
                        position_lots,
                        starting_wallet,
                    )
                    in_position = False
                    runner_open = False
                    if not partial_taken:
                        full_sl_count += 1
                        if entry_line == "upper":
                            upper_line_blocked = True
                        elif entry_line == "lower":
                            lower_line_blocked = True

            equity_curve.append(equity)
            continue

        if full_sl_count >= max_full_sl or trades_in_sequence >= max_trades:
            equity_curve.append(equity)
            continue

        if high >= upper:
            touched_upper = True
        if low <= lower:
            touched_lower = True

        if not touched_upper and not touched_lower:
            equity_curve.append(equity)
            continue

        if touched_upper and close < open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            candle_range = high - low
            if body_ratio >= min_signal_body_ratio and candle_range >= min_signal_range_points:
                pending_red = {
                    "high": high,
                    "low": low,
                    "index": index,
                }

        if touched_lower and close > open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            candle_range = high - low
            if body_ratio >= min_signal_body_ratio and candle_range >= min_signal_range_points:
                pending_green = {
                    "high": high,
                    "low": low,
                    "index": index,
                }

        can_enter_short = pending_red and (
            index > pending_red["index"] if entry_on_next_candle else True
        )
        if can_enter_short and low < pending_red["low"]:
            short_break_ok = (
                close < pending_red["low"] if require_close_beyond_signal else True
            )
            if short_break_ok:
                if upper_line_blocked or upper_entries_today >= max_entries_per_line:
                    pending_red = None
                    equity_curve.append(equity)
                    continue
                entry_price = close if require_close_beyond_signal else pending_red["low"]
                stop_loss = float(prev_row["high"]) if prev_row else pending_red["high"]
                target_1 = _points_target(entry_price, "short", partial_target_points)
                target_2 = _swing_low_before(daily_rows, day, swing_lookback)
                if (
                    _liquidity_entry_valid(
                        "short",
                        entry_price,
                        stop_loss,
                        partial_target_points,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                        max_sl_pct=max_sl_pct,
                    )
                    and target_2 > 0
                    and entry_price > target_2
                ):
                    in_position = True
                    side = "short"
                    entry_line = "upper"
                    entry_ts = timestamp
                    partial_taken = False
                    runner_open = False
                    trades_in_sequence += 1
                    upper_entries_today += 1
                    pending_red = None

        can_enter_long = pending_green and (
            index > pending_green["index"] if entry_on_next_candle else True
        )
        if can_enter_long and high > pending_green["high"]:
            long_break_ok = (
                close > pending_green["high"] if require_close_beyond_signal else True
            )
            if long_break_ok:
                if lower_line_blocked or lower_entries_today >= max_entries_per_line:
                    pending_green = None
                    equity_curve.append(equity)
                    continue
                entry_price = close if require_close_beyond_signal else pending_green["high"]
                stop_loss = float(prev_row["low"]) if prev_row else pending_green["low"]
                target_1 = _points_target(entry_price, "long", partial_target_points)
                target_2 = _swing_high_before(daily_rows, day, swing_lookback)
                if (
                    _liquidity_entry_valid(
                        "long",
                        entry_price,
                        stop_loss,
                        partial_target_points,
                        min_sl_points=min_sl_points,
                        max_sl_points=max_sl_points,
                        min_reward_to_risk=min_reward_to_risk,
                        max_sl_pct=max_sl_pct,
                    )
                    and target_2 > 0
                    and entry_price < target_2
                ):
                    in_position = True
                    side = "long"
                    entry_line = "lower"
                    entry_ts = timestamp
                    partial_taken = False
                    runner_open = False
                    trades_in_sequence += 1
                    lower_entries_today += 1
                    pending_green = None

        equity_curve.append(equity)

    if in_position:
        last = intraday_rows[-1]
        exit_price = float(last["close"])
        exit_lots = runner_lots if partial_taken else position_lots
        equity = _close_trade(
            trades,
            equity,
            entry_ts,
            last["timestamp"],
            entry_price,
            exit_price,
            "open_at_end",
            side,
            exit_lots,
            position_lots,
            starting_wallet,
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
        "uses_10_point_partial_target": partial_target_points == 10,
        "uses_5_point_partial_target": partial_target_points == 5,
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
    }

    result = _build_result(rule, trades, equity_curve, daily_rows, entry_based_win_rate=True)
    result.backtest_mode = "eth_100lots_filtered_entries"
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
    if rule.strategy_type == "liquidity" and intraday_rows and daily_rows:
        return backtest_liquidity_intraday(intraday_rows, daily_rows, rule)

    runners = {
        "ma_crossover": backtest_ma_crossover,
        "macd": backtest_macd,
        "breakout": backtest_breakout,
        "liquidity": backtest_liquidity,
    }
    runner = runners.get(rule.strategy_type)
    if runner is None:
        raise ValueError(f"Unsupported strategy type: {rule.strategy_type}")
    return runner(rows, rule)


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
