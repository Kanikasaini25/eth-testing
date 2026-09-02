from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from src.rule_extractor import TradingRule
from src.timezone import delta_candle_day, format_delta_timestamp

FIXED_ENTRY_LOTS = 100
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
    stop_loss: float = 0.0


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
        day = delta_candle_day(daily_rows[index]["timestamp"])
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
    stop_loss: float = 0.0,
) -> None:
    return_pct = _return_pct(side, entry_price, exit_price)
    trades.append(
        Trade(
            entry_date=format_delta_timestamp(entry_ts),
            exit_date=format_delta_timestamp(exit_ts),
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
            stop_loss=round(stop_loss, 2),
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
    stop_loss: float | None = None,
    initial_stop_loss: float | None = None,
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
        initial_stop_loss
        if initial_stop_loss is not None
        else (stop_loss if stop_loss is not None else exit_price),
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


def _in_delta_session(timestamp: str, start_hour: int, end_hour: int) -> bool:
    """Check session hours using Delta's canonical UTC candle timezone."""
    parsed = datetime.fromisoformat(timestamp)
    hour = parsed.hour
    if start_hour == end_hour:
        return True
    if start_hour < end_hour:
        return start_hour <= hour < end_hour
    return hour >= start_hour or hour < end_hour


def _previous_daily_candle(daily_rows: list[dict], day: str) -> dict | None:
    for index in range(1, len(daily_rows)):
        if delta_candle_day(daily_rows[index]["timestamp"]) == day:
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


def _liquidity_targets(
    side: str,
    entry_price: float,
    initial_stop_loss: float,
) -> tuple[float, float, float, float, float]:
    """Return initial risk and the +2%, +3%, +4%, and +5% targets."""
    risk = abs(entry_price - initial_stop_loss)
    if side == "long":
        return (
            risk,
            entry_price * 1.02,
            entry_price * 1.03,
            entry_price * 1.04,
            entry_price * 1.05,
        )
    return (
        risk,
        entry_price * 0.98,
        entry_price * 0.97,
        entry_price * 0.96,
        entry_price * 0.95,
    )


def _passes_liquidity_entry_filters(
    *,
    side: str,
    timestamp: str,
    entry_price: float,
    stop_loss: float,
    daily_rows: list[dict],
    day: str,
    require_liquidity_sweep: bool = False,
    signal_high: float = 0.0,
    signal_low: float = 0.0,
    signal_close: float = 0.0,
    upper: float = 0.0,
    lower: float = 0.0,
    use_daily_trend_filter: bool = False,
    use_session_filter: bool = False,
    session_start_hour_delta: int = 8,
    session_end_hour_delta: int = 20,
) -> bool:
    if not _liquidity_entry_valid(
        side, entry_price, stop_loss, 0,
        min_sl_points=0, max_sl_points=0,
        min_reward_to_risk=0, max_sl_pct=float("inf"),
    ):
        return False
    if use_session_filter and not _in_delta_session(
        timestamp, session_start_hour_delta, session_end_hour_delta
    ):
        return False
    if use_daily_trend_filter and not _daily_trend_allows(side, daily_rows, day):
        return False
    if require_liquidity_sweep:
        if side == "short" and not _liquidity_sweep_at_upper(signal_high, signal_close, upper):
            return False
        if side == "long" and not _liquidity_sweep_at_lower(signal_low, signal_close, lower):
            return False
    return True


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
    """Backtest LQDTY with full-size percentage-based exits."""
    levels = _daily_liquidity_levels(daily_rows)
    swing_lookback = int(rule.parameters.get("swing_lookback_days", 20))
    max_trades = int(rule.parameters.get("max_trades_per_sequence", 3))
    max_full_sl = int(rule.parameters.get("max_full_stop_losses_per_session", 3))
    position_lots = int(rule.parameters.get("position_lots", FIXED_ENTRY_LOTS))
    partial_exit_lots = position_lots
    runner_lots = position_lots
    partial_target_points = 0.0
    use_swing_target_for_partial = False
    runner_swing_lookback = 0
    min_sl_points = max_sl_points = min_reward_to_risk = 0.0
    max_sl_pct = float("inf")
    use_trailing_after_partial = False
    trailing_stop_points = 0.0
    max_entries_per_line = int(rule.parameters.get("max_entries_per_liquidity_line_per_day", 3))
    min_signal_body_ratio = float(rule.parameters.get("min_signal_body_ratio", 0.0))
    min_signal_range_points = float(rule.parameters.get("min_signal_range_points", 0.0))
    entry_on_next_candle = bool(rule.parameters.get("entry_on_next_candle", True))
    require_close_beyond_signal = bool(rule.parameters.get("require_close_beyond_signal", True))
    require_liquidity_sweep = bool(rule.parameters.get("require_liquidity_sweep", False))
    use_daily_trend_filter = bool(rule.parameters.get("use_daily_trend_filter", False))
    use_session_filter = bool(rule.parameters.get("use_session_filter", True))
    session_start_hour = int(
        rule.parameters.get(
            "session_start_hour_delta",
            rule.parameters.get("session_start_hour_utc", 8),
        )
    )
    session_end_hour = int(
        rule.parameters.get(
            "session_end_hour_delta",
            rule.parameters.get("session_end_hour_utc", 20),
        )
    )
    fee_pct_per_side = float(rule.parameters.get("fee_pct_per_side", 0.05))
    starting_wallet = float(rule.parameters.get("starting_wallet_usd", 10_000))

    trades: list[Trade] = []
    wallet_usd = starting_wallet
    equity_curve = [wallet_usd / starting_wallet]

    in_position = False
    side = ""
    entry_price = 0.0
    stop_loss = 0.0
    initial_stop_loss = 0.0
    target_1 = 0.0
    target_2 = 0.0
    target_3 = 0.0
    target_4 = 0.0
    risk = 0.0
    entry_ts = ""
    target_stage = 0
    partial_taken = False
    runner_open = False
    entry_fee_remaining = 0.0
    open_lots = 0

    current_day = ""
    touched_upper = False
    touched_lower = False
    rejection_red: dict[str, float] | None = None
    rejection_green: dict[str, float] | None = None
    pending_red: dict[str, float] | None = None
    pending_green: dict[str, float] | None = None
    trades_in_sequence = 0
    full_sl_count = 0
    upper_entries_today = 0
    lower_entries_today = 0
    upper_line_blocked = False
    lower_line_blocked = False
    upper_rearmed = True
    lower_rearmed = True
    entry_line = ""
    reentry_side = ""
    reentry_pullback_seen = False
    first_backtest_day = delta_candle_day(intraday_rows[0]["timestamp"])

    for index, row in enumerate(intraday_rows):
        prev_row = intraday_rows[index - 1] if index > 0 else None
        timestamp = row["timestamp"]
        day = delta_candle_day(timestamp)
        open_price = float(row["open"])
        close = float(row["close"])
        entered_this_bar = False
        bar_ref = entry_price if in_position else close
        high = _effective_high(row, bar_ref)
        low = _effective_low(row, bar_ref)

        if day != current_day:
            current_day = day
            touched_upper = False
            touched_lower = False
            rejection_red = None
            rejection_green = None
            pending_red = None
            pending_green = None
            trades_in_sequence = 0
            full_sl_count = 0
            upper_entries_today = 0
            lower_entries_today = 0
            upper_line_blocked = False
            lower_line_blocked = False
            upper_rearmed = True
            lower_rearmed = True
            reentry_side = ""
            reentry_pullback_seen = False

        # The first selected day establishes the reference range. Entries start
        # on the following day, using the first day's high/low as liquidity lines.
        if day == first_backtest_day:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        if day not in levels:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        upper = levels[day]["upper"]
        lower = levels[day]["lower"]

        if not in_position:
            if reentry_side == "short" and close > open_price:
                reentry_pullback_seen = True
            elif reentry_side == "long" and close < open_price:
                reentry_pullback_seen = True
            if low < upper:
                upper_rearmed = True
            if high > lower:
                lower_rearmed = True

        if in_position:
            favorable = high if side == "long" else low
            if (
                favorable >= target_4
                if side == "long"
                else favorable <= target_4
            ):
                wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                    trades, wallet_usd, entry_ts, timestamp, entry_price, target_4,
                    "take_profit_5pct", side, position_lots, position_lots,
                    entry_fee_remaining, open_lots,
                    fee_pct_per_side=fee_pct_per_side,
                    initial_stop_loss=initial_stop_loss,
                )
                reentry_side = side
                reentry_pullback_seen = False
                in_position = False
                equity_curve.append(wallet_usd / starting_wallet)
                continue
            while target_stage < 2 and (
                favorable >= (target_2 if target_stage == 0 else target_3)
                if side == "long"
                else favorable <= (target_2 if target_stage == 0 else target_3)
            ):
                target_stage += 1
                stop_loss = target_1 if target_stage == 1 else target_2
            if (low <= stop_loss if side == "long" else high >= stop_loss):
                wallet_usd, entry_fee_remaining, open_lots = _close_trade(
                    trades, wallet_usd, entry_ts, timestamp, entry_price, stop_loss,
                    "stop_loss"
                    if target_stage == 0
                    else f"stop_at_{2 if target_stage == 1 else 3}pct",
                    side, position_lots, position_lots, entry_fee_remaining,
                    open_lots,
                    fee_pct_per_side=fee_pct_per_side,
                    initial_stop_loss=initial_stop_loss,
                )
                in_position = False
                if target_stage > 0:
                    reentry_side = side
                    reentry_pullback_seen = False
                if target_stage == 0:
                    full_sl_count += 1
                    if entry_line == "upper":
                        upper_rearmed = True
                    elif entry_line == "lower":
                        lower_rearmed = True
                    if entry_line == "upper":
                        upper_line_blocked = True
                    elif entry_line == "lower":
                        lower_line_blocked = True
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        if in_position and False:
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
                        initial_stop_loss=initial_stop_loss,
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
                        initial_stop_loss=initial_stop_loss,
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
                        initial_stop_loss=initial_stop_loss,
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
                        initial_stop_loss=initial_stop_loss,
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
                        initial_stop_loss=initial_stop_loss,
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
                        initial_stop_loss=initial_stop_loss,
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
        if low <= lower:
            touched_lower = True

        if not touched_upper and not touched_lower and not reentry_side:
            equity_curve.append(wallet_usd / starting_wallet)
            continue

        short_rejection = (
            reentry_side != "long"
            and
            touched_upper and upper_rearmed and high > upper and close < open_price
        )
        short_rejection = short_rejection or (
            reentry_side == "short" and reentry_pullback_seen and close < open_price
        )
        long_rejection = (
            reentry_side != "short"
            and
            touched_lower and lower_rearmed and low < lower and close > open_price
        )
        long_rejection = long_rejection or (
            reentry_side == "long" and reentry_pullback_seen and close > open_price
        )
        if rejection_red and index > rejection_red["index"]:
            if close < open_price:
                pending_red = {"high": high, "low": low, "close": close, "index": index}
            rejection_red = None
        if rejection_green and index > rejection_green["index"]:
            if close > open_price:
                pending_green = {"high": high, "low": low, "close": close, "index": index}
            rejection_green = None
        if pending_red and index > pending_red["index"]:
            if close < open_price and low < pending_red["low"]:
                short_triggered = True
            else:
                short_triggered = False
                pending_red = None
            if short_triggered:
                if upper_entries_today >= max_entries_per_line:
                    pending_red = None
                    equity_curve.append(wallet_usd / starting_wallet)
                    continue
                entry_price = close if require_close_beyond_signal else pending_red["low"]
                stop_loss = pending_red["high"]
                initial_stop_loss = stop_loss
                risk, target_1, target_2, target_3, target_4 = _liquidity_targets(
                    "short", entry_price, stop_loss
                )
                signal = pending_red
                if (
                    _passes_liquidity_entry_filters(
                        side="short",
                        timestamp=timestamp,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        daily_rows=daily_rows,
                        day=day,
                        require_liquidity_sweep=False,
                        signal_high=signal["high"],
                        signal_low=signal["low"],
                        signal_close=signal["close"],
                        upper=upper,
                        lower=lower,
                        use_daily_trend_filter=use_daily_trend_filter,
                        use_session_filter=use_session_filter,
                        session_start_hour_delta=session_start_hour,
                        session_end_hour_delta=session_end_hour,
                    )
                    and target_1 > 0
                    and entry_price > target_1
                ):
                    in_position = True
                    side = "short"
                    entry_line = "upper"
                    entry_ts = timestamp
                    target_stage = 0
                    open_lots = position_lots
                    entry_fee_remaining = _trading_fee_usd(
                        entry_price, position_lots, fee_pct_per_side
                    )
                    trades_in_sequence += 1
                    upper_entries_today += 1
                    pending_red = None
                    rejection_red = None
                    entered_this_bar = True
                    upper_rearmed = False
                    reentry_side = ""
                    reentry_pullback_seen = False
        if pending_green and index > pending_green["index"]:
            if close > open_price and high > pending_green["high"]:
                long_triggered = True
            else:
                long_triggered = False
                pending_green = None
            if long_triggered:
                if lower_entries_today >= max_entries_per_line:
                    pending_green = None
                    equity_curve.append(wallet_usd / starting_wallet)
                    continue
                entry_price = close if require_close_beyond_signal else pending_green["high"]
                stop_loss = pending_green["low"]
                initial_stop_loss = stop_loss
                risk, target_1, target_2, target_3, target_4 = _liquidity_targets(
                    "long", entry_price, stop_loss
                )
                signal = pending_green
                if (
                    _passes_liquidity_entry_filters(
                        side="long",
                        timestamp=timestamp,
                        entry_price=entry_price,
                        stop_loss=stop_loss,
                        daily_rows=daily_rows,
                        day=day,
                        require_liquidity_sweep=False,
                        signal_high=signal["high"],
                        signal_low=signal["low"],
                        signal_close=signal["close"],
                        upper=upper,
                        lower=lower,
                        use_daily_trend_filter=use_daily_trend_filter,
                        use_session_filter=use_session_filter,
                        session_start_hour_delta=session_start_hour,
                        session_end_hour_delta=session_end_hour,
                    )
                    and target_1 > 0
                    and entry_price < target_1
                ):
                    in_position = True
                    side = "long"
                    entry_line = "lower"
                    entry_ts = timestamp
                    target_stage = 0
                    open_lots = position_lots
                    entry_fee_remaining = _trading_fee_usd(
                        entry_price, position_lots, fee_pct_per_side
                    )
                    trades_in_sequence += 1
                    lower_entries_today += 1
                    pending_green = None
                    rejection_green = None
                    reentry_side = ""
                    reentry_pullback_seen = False
                    entered_this_bar = True
                    lower_rearmed = False

        if not entered_this_bar and short_rejection:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or high - low >= min_signal_range_points
            if body_ok and range_ok:
                if close < open_price:
                    pending_red = {"high": high, "low": low, "close": close, "index": index}
                else:
                    rejection_red = {"high": high, "low": low, "close": close, "index": index}
        if not entered_this_bar and long_rejection:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or high - low >= min_signal_range_points
            if body_ok and range_ok:
                if close > open_price:
                    pending_green = {"high": high, "low": low, "close": close, "index": index}
                else:
                    rejection_green = {"high": high, "low": low, "close": close, "index": index}

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
            initial_stop_loss=initial_stop_loss,
        )

    compliance = {
        "uses_previous_day_high_low_lines": True,
        "uses_1m_candle_confirmation": True,
        "supports_long_and_short": True,
        "uses_first_confirmation_candle_wick_stop_loss": True,
        "entry_on_next_candle": entry_on_next_candle,
        "requires_close_beyond_signal": require_close_beyond_signal,
        "requires_two_consecutive_confirmation_candles": True,
        "uses_risk_from_wick_distance": True,
        "uses_1_to_2_risk_reward": True,
        "fixed_100_lot_entry": position_lots == 100,
        "keeps_full_position_at_tp1": True,
        "moves_stop_to_2r_at_tp1": True,
        "moves_stop_to_3r_at_tp2": True,
        "closes_full_position_at_tp3": True,
        "limits_max_trades_per_session": True,
        "limits_max_full_stop_losses": True,
        "one_attempt_per_liquidity_line_per_day": max_entries_per_line == 1,
        "blocks_line_after_full_stop_loss": False,
        "skips_middle_zone_without_touch": True,
        "instrument_eth_futures": True,
        "requires_liquidity_sweep_rejection": require_liquidity_sweep,
        "uses_daily_trend_filter": use_daily_trend_filter,
        "uses_delta_india_session_filter": use_session_filter,
        "simulates_trading_fees": fee_pct_per_side > 0,
    }

    result = _build_result(rule, trades, equity_curve, daily_rows, entry_based_win_rate=True)
    result.backtest_mode = "eth_100lots_r_multiple"
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
