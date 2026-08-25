from __future__ import annotations

from src.trade_filters import entry_reward_points, entry_target_price


def lots_for_risk(
    wallet: float,
    stop_points: float,
    *,
    risk_pct: float,
    usd_per_point: float = 1.0,
    min_lots: int = 1,
    max_lots: int = 20,
    use_risk_sizing: bool = True,
    fallback_lots: int = 20,
    entry_price: float = 0.0,
    max_leverage: float = 1.0,
) -> int:
    if stop_points <= 0:
        return 0
    if not use_risk_sizing:
        lots = max(min_lots, min(int(fallback_lots), max_lots))
    else:
        risk_usd = wallet * (risk_pct / 100.0)
        raw = int(risk_usd / (stop_points * usd_per_point))
        if raw < min_lots:
            return 0
        lots = min(raw, max_lots)
    if max_leverage > 0 and entry_price > 0 and wallet > 0:
        cap = int((wallet * max_leverage) / (entry_price * usd_per_point))
        lots = min(lots, cap)
    if lots < min_lots:
        return 0
    return lots


def reward_from_fill(
    fill: float,
    stop_loss: float,
    min_target: float,
    reward_r: float,
) -> float:
    return entry_reward_points(abs(fill - stop_loss), min_target, reward_r)


def target_from_fill(
    side: str,
    fill: float,
    stop_loss: float,
    min_target: float,
    reward_r: float,
) -> float:
    return entry_target_price(
        side,
        fill,
        reward_from_fill(fill, stop_loss, min_target, reward_r),
    )


def fill_risk_allowed(
    fill: float,
    stop_loss: float,
    *,
    max_sl_points: float,
    min_reward_to_risk: float,
    min_target: float,
    reward_r: float,
) -> bool:
    distance = abs(fill - stop_loss)
    if max_sl_points > 0 and distance > max_sl_points:
        return False
    reward = reward_from_fill(fill, stop_loss, min_target, reward_r)
    if min_reward_to_risk > 0 and distance > 0 and (reward / distance) < min_reward_to_risk:
        return False
    return True


def day_loss_reached(day_start_wallet: float, wallet: float, daily_loss_pct: float) -> bool:
    if daily_loss_pct <= 0 or day_start_wallet <= 0:
        return False
    return (wallet - day_start_wallet) <= -(day_start_wallet * daily_loss_pct / 100.0)


def reached_r(
    side: str,
    fill: float,
    original_stop: float,
    high: float,
    low: float,
    r_multiple: float = 1.0,
) -> bool:
    risk = abs(fill - original_stop)
    if risk <= 0 or r_multiple <= 0:
        return False
    move = risk * r_multiple
    if side == "long":
        return high >= fill + move
    return low <= fill - move


def reached_one_r(side: str, fill: float, original_stop: float, high: float, low: float) -> bool:
    return reached_r(side, fill, original_stop, high, low, r_multiple=1.0)
