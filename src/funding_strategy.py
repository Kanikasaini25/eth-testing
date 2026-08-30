from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import MIN_ONE_SIDED_SHARE, STRATEGY_FUNDING
from src.strategy import EntrySignal, StrategyParams

FUNDING_HOURS = (0, 8, 16)


def funding_rate_pct(row: dict) -> float:
    if "funding_rate" in row and row["funding_rate"] is not None:
        return float(row["funding_rate"])
    return float(row["close"])


def is_settlement_bar(timestamp: str, interval_hours: int) -> bool:
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.astimezone(timezone.utc).hour
    if interval_hours >= 8:
        return hour in FUNDING_HOURS and dt.minute == 0
    return dt.minute == 0 and hour % max(interval_hours, 1) == 0


def settlement_rates(funding_rows: list[dict], params: StrategyParams) -> list[dict]:
    out: list[dict] = []
    for row in funding_rows:
        ts = row.get("timestamp")
        if not ts:
            continue
        if is_settlement_bar(str(ts), params.funding_interval_hours):
            out.append({"timestamp": ts, "rate": funding_rate_pct(row)})
    if out:
        return out
    return [{"timestamp": row["timestamp"], "rate": funding_rate_pct(row)} for row in funding_rows]


def last_rates(funding_rows: list[dict], params: StrategyParams) -> list[float]:
    settled = settlement_rates(funding_rows, params)
    needed = max(params.funding_confirm_periods, 1)
    return [item["rate"] for item in settled[-needed:]]


def reading_rates(funding_rows: list[dict], count: int) -> list[float]:
    needed = max(count, 1)
    return [funding_rate_pct(row) for row in funding_rows[-needed:]]


def carry_direction(rates: list[float], params: StrategyParams) -> str | None:
    needed = params.funding_confirm_periods
    if len(rates) < needed:
        return None
    window = rates[-needed:]
    floor = params.funding_threshold_pct
    if all(rate > 0 for rate in window) and all(abs(rate) >= floor for rate in window):
        return "carry"
    if all(rate < 0 for rate in window) and all(abs(rate) >= floor for rate in window):
        return "reverse"
    return None


def abs_rate_rising(rates: list[float]) -> bool:
    if len(rates) < 2:
        return False
    return abs(rates[-1]) > abs(rates[-2])


def minutes_until_settlement(timestamp: str) -> int:
    dt = datetime.fromisoformat(timestamp)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    if dt.hour in FUNDING_HOURS and dt.minute == 0:
        return 0
    if dt.hour < 8:
        next_hour = 8
    elif dt.hour < 16:
        next_hour = 16
    else:
        next_hour = 24
    return (next_hour - dt.hour) * 60 - dt.minute


def skip_near_settlement(timestamp: str, rate: float, params: StrategyParams) -> bool:
    skip = params.funding_skip_minutes_before_settle
    if skip <= 0:
        return False
    minutes = minutes_until_settlement(timestamp)
    if not (0 < minutes <= skip):
        return False
    return abs(rate) < params.funding_strong_rate_pct


@dataclass
class FundingScreen:
    symbol: str
    readings: int
    positive: int
    negative: int
    one_sided_share: float
    dominant: str
    tradable: bool
    note: str


def screen_funding_history(
    funding_rows: list[dict],
    symbol: str = "",
    min_share: float = MIN_ONE_SIDED_SHARE,
) -> FundingScreen:
    """Reject books whose funding flips constantly.

    A carry only pays if the rate stays on one side long enough to outrun the
    round trip. Over the last year ETH and BTC were ~78% one-sided and traded
    3-4 times; SOL was 54% and churned 120 times into a loss.
    """
    rates = [funding_rate_pct(row) for row in funding_rows]
    total = len(rates)
    if not total:
        return FundingScreen(symbol, 0, 0, 0, 0.0, "none", False, "no funding history")
    positive = sum(1 for rate in rates if rate > 0)
    negative = sum(1 for rate in rates if rate < 0)
    dominant = "negative" if negative >= positive else "positive"
    share = max(positive, negative) / total
    tradable = share >= min_share
    if tradable:
        note = f"{share:.0%} {dominant}, holds should last"
    else:
        note = f"only {share:.0%} {dominant}, expect churn and fee drag"
    return FundingScreen(symbol, total, positive, negative, share, dominant, tradable, note)


def completed_run_lengths(rates: list[float]) -> list[int]:
    runs: list[int] = []
    sign = 0
    count = 0
    for rate in rates:
        current = 1 if rate > 0 else -1 if rate < 0 else 0
        if current == 0:
            if sign != 0:
                runs.append(count)
            sign = 0
            count = 0
            continue
        if current == sign:
            count += 1
            continue
        if sign != 0:
            runs.append(count)
        sign = current
        count = 1
    return runs


def expected_hold_settlements(funding_rows: list[dict], params: StrategyParams) -> int:
    rates = [item["rate"] for item in settlement_rates(funding_rows, params)]
    runs = completed_run_lengths(rates)
    floor = max(params.funding_min_settlements, 1)
    if len(runs) < 3:
        return floor
    median = sorted(runs)[len(runs) // 2]
    return max(floor, min(int(median), 48))


def round_trip_fees(price: float, params: StrategyParams) -> float:
    """Two futures legs + two spot legs. Futures can be maker; spot stays taker."""
    size = params.position_lots * params.contract_value
    taker = params.fee_pct_per_side / 100.0
    maker = params.fee_maker_pct / 100.0
    gst = 1.0 + params.gst_pct / 100.0
    fut = maker if params.funding_futures_maker else taker
    return 2.0 * price * size * gst * (fut + taker)


def four_leg_taker_fees(price: float, params: StrategyParams) -> float:
    return round_trip_fees(price, params)


def expected_funding_usd(rate_pct: float, price: float, params: StrategyParams, settlements: int) -> float:
    return abs(funding_payment_usd(rate_pct, price, params, "carry")) * settlements


def funding_edge_covers_fees(
    rate_pct: float,
    price: float,
    params: StrategyParams,
    funding_rows: list[dict],
) -> bool:
    holds = expected_hold_settlements(funding_rows, params)
    edge = expected_funding_usd(rate_pct, price, params, holds)
    cost = round_trip_fees(price, params) * max(params.funding_fee_margin, 0.0)
    return edge > cost


def should_enter_from_rates(rates: list[float], params: StrategyParams) -> bool:
    return carry_direction(rates, params) == "carry"


def should_enter_carry(funding_rows: list[dict], params: StrategyParams) -> bool:
    return carry_direction(last_rates(funding_rows, params), params) == "carry"


def should_exit_hedge(
    rate: float,
    side: str,
    recent: list[float] | None = None,
    confirm: int = 1,
) -> bool:
    needed = max(confirm, 1)
    window = (recent if recent is not None else [rate])[-needed:]
    if len(window) < needed:
        return False
    if side == "reverse":
        return all(item > 0.0 for item in window)
    return all(item < 0.0 for item in window)


def should_exit_carry(current_rate: float) -> bool:
    return should_exit_hedge(current_rate, "carry")


def detect_funding_signal(
    funding_rows: list[dict],
    price_rows: list[dict],
    params: StrategyParams,
    in_carry: bool = False,
    current_rate: float | None = None,
    position_side: str = "",
) -> EntrySignal | None:
    """Enter when |funding| is stably rich; flip the hedge when the sign changes."""
    if not price_rows:
        return None
    last = price_rows[-1]
    price = float(last["close"])
    rate = current_rate
    if rate is None and funding_rows:
        rate = funding_rate_pct(funding_rows[-1])
    if rate is None:
        return None

    side = position_side or ("carry" if in_carry else "")
    if side in {"carry", "reverse"}:
        confirm = max(params.funding_exit_confirm, 1)
        recent = reading_rates(funding_rows, confirm)
        if current_rate is not None and (not recent or recent[-1] != current_rate):
            recent = (recent + [current_rate])[-confirm:]
        if not should_exit_hedge(rate, side, recent, confirm):
            return None
        return EntrySignal(
            strategy=STRATEGY_FUNDING,
            side="cover",
            entry_ts=last["timestamp"],
            entry_price=price,
            stop_loss=0.0,
            target=0.0,
            order_type="limit" if params.funding_futures_maker else "market",
            reason="funding_flip",
            extras={"funding_rate": rate, "closed_side": side},
        )

    direction = carry_direction(last_rates(funding_rows, params), params)
    if direction is None:
        return None
    settled = last_rates(funding_rows, params)
    if params.funding_require_momentum and not abs_rate_rising(settled):
        return None
    if skip_near_settlement(last["timestamp"], rate, params):
        return None
    if current_rate is not None:
        if direction == "carry" and current_rate < params.funding_threshold_pct:
            return None
        if direction == "reverse" and current_rate > -params.funding_threshold_pct:
            return None
    if not funding_edge_covers_fees(rate, price, params, funding_rows):
        return None
    holds = expected_hold_settlements(funding_rows, params)
    return EntrySignal(
        strategy=STRATEGY_FUNDING,
        side=direction,
        entry_ts=last["timestamp"],
        entry_price=price,
        stop_loss=0.0,
        target=0.0,
        order_type="limit" if params.funding_futures_maker else "market",
        reason="funding_positive" if direction == "carry" else "funding_negative",
        extras={
            "funding_rate": rate,
            "spot_symbol": params.spot_symbol,
            "futures_symbol": params.futures_symbol,
            "hedge_qty": params.hedge_qty(),
            "hold_settlements": holds,
            "expected_funding": round(expected_funding_usd(rate, price, params, holds), 2),
            "fee_hurdle": round(round_trip_fees(price, params) * max(params.funding_fee_margin, 0.0), 2),
        },
    )


def funding_payment_usd(
    rate_pct: float,
    price: float,
    params: StrategyParams,
    side: str = "carry",
) -> float:
    """Carry (short perp) receives positive funding. Reverse (long perp) receives negative."""
    signed = params.hedge_qty() * price * (rate_pct / 100.0)
    return -signed if side == "reverse" else signed


def run_funding_backtest(
    price_rows: list[dict],
    funding_rows: list[dict],
    params: StrategyParams,
    entry_log: list[EntrySignal] | None = None,
):
    from src.backtest import close_trade, finish_backtest, open_from_signal

    rate_by_ts = {row["timestamp"]: float(row["close"]) for row in funding_rows}
    position = None
    trades: list[dict] = []
    wallet = params.starting_wallet_usd
    lots = params.position_lots
    seen: list[dict] = []
    for bar in price_rows:
        ts = bar["timestamp"]
        if ts in rate_by_ts:
            seen.append({"timestamp": ts, "close": rate_by_ts[ts]})
        current_rate = rate_by_ts.get(ts)
        if position is not None and current_rate is not None:
            if is_settlement_bar(ts, params.funding_interval_hours):
                position.funding_pnl += funding_payment_usd(
                    current_rate, float(bar["close"]), params, position.side
                )
        signal = detect_funding_signal(
            seen,
            [bar],
            params,
            position_side=position.side if position is not None else "",
            current_rate=current_rate,
        )
        if signal is None:
            continue
        if signal.side in {"carry", "reverse"} and position is None:
            if entry_log is not None:
                entry_log.append(signal)
            position = open_from_signal(signal, lots)
            continue
        if signal.side == "cover" and position is not None:
            trade, wallet = close_trade(
                position,
                bar["timestamp"],
                float(bar["close"]),
                "funding_flip",
                wallet,
                params,
                extra_legs=2,
            )
            trades.append(trade)
            position = None
    extra = {
        "last_close": float(price_rows[-1]["close"]) if price_rows else 0.0,
        "pending_note": f"in {position.side}" if position is not None else "",
    }
    return finish_backtest(price_rows, trades, position, wallet, params, extra, extra_legs=2)