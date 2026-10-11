"""Paper-trade confirmation: enter only after price moves N points in the trade direction."""

from __future__ import annotations

PENDING = "pending"
CONFIRMED = "confirmed"
FAILED = "failed"


def confirm_profit_points(params: dict) -> float:
    """Points price must move in the trade direction before entering; 0 disables confirmation."""
    return max(float(params.get("confirm_profit_points", 0) or 0), 0.0)


def confirmation_trigger(side: str, entry_price: float, points: float) -> float:
    """Price level that confirms a paper signal for the given side."""
    if side == "long":
        return entry_price + points
    if side == "short":
        return entry_price - points
    raise ValueError(f"Unknown trade side: {side!r}")


def confirmation_status(
    side: str,
    trigger: float,
    stop_loss: float,
    high: float,
    low: float,
) -> str:
    """Classify a bar against a pending paper trade.

    When a single bar touches both the stop and the trigger, the intrabar order is
    unknown, so the stop is assumed to have been hit first.
    """
    if side == "long":
        stop_hit = low <= stop_loss
        trigger_hit = high >= trigger
    elif side == "short":
        stop_hit = high >= stop_loss
        trigger_hit = low <= trigger
    else:
        raise ValueError(f"Unknown trade side: {side!r}")

    if stop_hit:
        return FAILED
    if trigger_hit:
        return CONFIRMED
    return PENDING
