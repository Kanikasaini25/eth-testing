"""Fixed 100-lot sizing. $3.50 stop / $10 TP map to price distance at 1 ETH notional."""

from __future__ import annotations

from dataclasses import dataclass

from src.config import DEFAULT_CONTRACT_ETH, FIXED_LOTS, TAKER_FEE_PCT
from src.errors import StrategyError


@dataclass(frozen=True)
class TradePlan:
    side: str
    lots: int
    entry_price: float
    stop_price: float
    take_profit_price: float
    profit_lock_price: float
    max_profit_price: float
    sl_distance: float
    risk_usd: float
    reward_usd: float
    contract_eth: float


def round_to_tick(price: float, tick_size: float) -> float:
    if tick_size <= 0:
        return round(price, 2)
    ticks = round(price / tick_size)
    return round(ticks * tick_size, 10)


def price_pnl_usd(side: str, entry: float, exit_price: float, lots: int, contract_eth: float) -> float:
    move = exit_price - entry
    if side == "short":
        move = -move
    return move * lots * contract_eth


def trade_risk_reward(
    *,
    side: str,
    entry_price: float,
    stop_price: float,
    take_profit_price: float,
    lots: int,
    contract_eth: float,
    realized_pnl: float = 0.0,
) -> dict[str, float]:
    """Planned risk, planned reward, R:R (reward per $1 risk), and realized R."""
    risk_usd = abs(price_pnl_usd(side, entry_price, stop_price, lots, contract_eth))
    reward_usd = abs(price_pnl_usd(side, entry_price, take_profit_price, lots, contract_eth))
    ratio = reward_usd / risk_usd if risk_usd > 0 else 0.0
    realized_r = realized_pnl / risk_usd if risk_usd > 0 else 0.0
    return {
        "risk_usd": risk_usd,
        "reward_usd": reward_usd,
        "ratio": ratio,
        "realized_r": realized_r,
    }


def trading_fee_usd(
    price: float,
    lots: int,
    contract_eth: float,
    fee_pct_per_side: float = TAKER_FEE_PCT,
) -> float:
    """Delta charge: percent of notional. 0.05 = 0.05% taker (same as LQDTY)."""
    if price <= 0 or lots <= 0 or contract_eth <= 0 or fee_pct_per_side <= 0:
        return 0.0
    notional = price * lots * contract_eth
    return notional * fee_pct_per_side / 100.0


def estimated_round_trip_fee_usd(
    entry_price: float,
    lots: int,
    contract_eth: float,
    fee_pct_per_side: float = TAKER_FEE_PCT,
) -> float:
    """Two taker fills at entry notional. Exit price is close enough for target placement."""
    return 2.0 * trading_fee_usd(entry_price, lots, contract_eth, fee_pct_per_side)


def gross_target_usd(
    net_usd: float,
    entry_price: float,
    lots: int,
    contract_eth: float,
    fee_pct_per_side: float,
    *,
    net_of_fees: bool,
) -> float:
    if not net_of_fees:
        return net_usd
    return net_usd + estimated_round_trip_fee_usd(
        entry_price, lots, contract_eth, fee_pct_per_side
    )


def exact_stop_distance(lots: int, risk_usd: float, contract_eth: float) -> float:
    """Recompute price distance so integer lots risk exactly risk_usd."""
    notional_per_point = lots * contract_eth
    if notional_per_point <= 0:
        raise StrategyError("Position notional is zero")
    return risk_usd / notional_per_point


def target_price(side: str, entry: float, target_usd: float, lots: int, contract_eth: float) -> float:
    distance = exact_stop_distance(lots, target_usd, contract_eth)
    if side == "long":
        return entry + distance
    return entry - distance


def stop_price(side: str, entry: float, sl_distance: float) -> float:
    if side == "long":
        return entry - sl_distance
    return entry + sl_distance


def stop_hit(side: str, mark: float, stop: float) -> bool:
    if side == "long":
        return mark <= stop
    return mark >= stop


def take_profit_hit(side: str, mark: float, take_profit: float) -> bool:
    if side == "long":
        return mark >= take_profit
    return mark <= take_profit


def trail_lock_price(side: str, mark: float, lock_price: float, entry: float) -> float:
    """Keep at least the +$5 lock while price runs toward +$20."""
    lock_distance = abs(lock_price - entry)
    if side == "long":
        return max(lock_price, mark - lock_distance)
    return min(lock_price, mark + lock_distance)


def bar_stop_hit(side: str, low: float, high: float, stop: float) -> bool:
    if side == "long":
        return low <= stop
    return high >= stop


def bar_target_hit(side: str, low: float, high: float, target: float) -> bool:
    if side == "long":
        return high >= target
    return low <= target


def build_trade_plan(
    *,
    side: str,
    entry_price: float,
    candle_low: float,
    candle_high: float,
    risk_usd: float,
    take_profit_usd: float,
    profit_lock_usd: float,
    max_profit_usd: float,
    contract_eth: float = DEFAULT_CONTRACT_ETH,
    tick_size: float = 0.05,
    lots: int = FIXED_LOTS,
    fee_pct_per_side: float = TAKER_FEE_PCT,
    net_of_fees: bool = True,
    stop_override: float | None = None,
) -> TradePlan:
    _ = (candle_low, candle_high)
    lots = FIXED_LOTS
    if stop_override is not None:
        sl = round_to_tick(stop_override, tick_size)
    else:
        exact_distance = exact_stop_distance(lots, risk_usd, contract_eth)
        sl = round_to_tick(stop_price(side, entry_price, exact_distance), tick_size)
    tp_gross = gross_target_usd(
        take_profit_usd, entry_price, lots, contract_eth, fee_pct_per_side, net_of_fees=net_of_fees
    )
    lock_gross = gross_target_usd(
        profit_lock_usd, entry_price, lots, contract_eth, fee_pct_per_side, net_of_fees=net_of_fees
    )
    max_gross = gross_target_usd(
        max_profit_usd, entry_price, lots, contract_eth, fee_pct_per_side, net_of_fees=net_of_fees
    )
    tp = round_to_tick(target_price(side, entry_price, tp_gross, lots, contract_eth), tick_size)
    lock = round_to_tick(target_price(side, entry_price, lock_gross, lots, contract_eth), tick_size)
    max_tp = round_to_tick(target_price(side, entry_price, max_gross, lots, contract_eth), tick_size)
    actual_risk = abs(price_pnl_usd(side, entry_price, sl, lots, contract_eth))
    return TradePlan(
        side=side,
        lots=lots,
        entry_price=entry_price,
        stop_price=sl,
        take_profit_price=tp,
        profit_lock_price=lock,
        max_profit_price=max_tp,
        sl_distance=abs(entry_price - sl),
        risk_usd=actual_risk,
        reward_usd=tp_gross,
        contract_eth=contract_eth,
    )
