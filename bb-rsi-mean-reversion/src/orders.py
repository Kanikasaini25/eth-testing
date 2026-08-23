"""Entry plus synthetic/native bracket SL + TP. Isolated from the LQDTY order path."""

from __future__ import annotations

from src.delta_client import DeltaClient
from src.errors import OrderError
from src.logger import setup_logger
from src.risk import TradePlan, round_to_tick
from src.state import OpenPosition
from src.session import utc_now

logger = setup_logger()


def _exit_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def _entry_side(side: str) -> str:
    return "buy" if side == "long" else "sell"


def _sl_limit(plan: TradePlan, tick: float) -> float:
    """Give the stop a tick of room so it can fill as a limit after trigger."""
    if plan.side == "long":
        return round_to_tick(plan.stop_price - tick, tick)
    return round_to_tick(plan.stop_price + tick, tick)


class OrderExecutor:
    def __init__(self, client: DeltaClient, dry_run: bool = False) -> None:
        self.client = client
        self.dry_run = dry_run

    def enter(self, plan: TradePlan) -> OpenPosition:
        if self.dry_run:
            logger.info("DRY RUN skip live order lots=%s side=%s", plan.lots, plan.side)
            return self._position_from_plan(plan, entry_order_id=None)

        orphan = self.client.get_position_size()
        if orphan != 0:
            raise OrderError(
                f"Entry blocked: exchange already has {orphan} lots. Flatten before this bot trades."
            )
        if self.client.trading_status() != "operational":
            raise OrderError(f"Market not operational: {self.client.trading_status()}")

        order = self._place_entry_with_bracket(plan)
        try:
            self._ensure_bracket(plan)
        except Exception as exc:  # noqa: BLE001
            logger.error("Bracket failed after entry — rolling back: %s", exc)
            self.client.close_position_market()
            self.client.cancel_open_orders()
            raise OrderError(f"Entry rolled back; bracket failed: {exc}") from exc

        order_id = None
        if isinstance(order, dict):
            order_id = order.get("id")
        return self._position_from_plan(plan, entry_order_id=order_id)

    def _place_entry_with_bracket(self, plan: TradePlan) -> dict:
        tick = self.client.tick_size()
        payload = {
            "size": plan.lots,
            "side": _entry_side(plan.side),
            "order_type": "market_order",
            "bracket_stop_loss_price": str(plan.stop_price),
            "bracket_stop_loss_limit_price": str(_sl_limit(plan, tick)),
            "bracket_take_profit_price": str(plan.take_profit_price),
            "bracket_take_profit_limit_price": str(plan.take_profit_price),
            "bracket_stop_trigger_method": "mark_price",
            "client_order_id": f"bbrsi{int(utc_now().timestamp() * 1000)}"[:32],
        }
        try:
            return self.client.place_order(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Native bracket entry failed (%s) — placing market only", exc)
            return self.client.place_order(
                {
                    "size": plan.lots,
                    "side": _entry_side(plan.side),
                    "order_type": "market_order",
                    "client_order_id": f"bbrsim{int(utc_now().timestamp() * 1000)}"[:32],
                }
            )

    def _ensure_bracket(self, plan: TradePlan) -> None:
        existing = self.client.get_open_orders()
        if len(existing) >= 2:
            return
        tick = self.client.tick_size()
        stop_side = _exit_side(plan.side)
        try:
            self.client.place_bracket(
                {
                    "stop_loss_order": {
                        "order_type": "limit_order",
                        "stop_price": str(plan.stop_price),
                        "limit_price": str(_sl_limit(plan, tick)),
                    },
                    "take_profit_order": {
                        "order_type": "limit_order",
                        "stop_price": str(plan.take_profit_price),
                        "limit_price": str(plan.take_profit_price),
                    },
                    "bracket_stop_trigger_method": "mark_price",
                }
            )
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("POST /orders/bracket failed (%s) — using separate SL/TP", exc)

        self.client.place_order(
            {
                "size": plan.lots,
                "side": stop_side,
                "order_type": "limit_order",
                "stop_order_type": "stop_loss_order",
                "stop_price": str(plan.stop_price),
                "limit_price": str(_sl_limit(plan, tick)),
                "reduce_only": True,
            }
        )
        self.client.place_order(
            {
                "size": plan.lots,
                "side": stop_side,
                "order_type": "limit_order",
                "limit_price": str(plan.take_profit_price),
                "reduce_only": True,
            }
        )

    def update_stop(self, position: OpenPosition, new_stop: float) -> None:
        if self.dry_run:
            return
        tick = self.client.tick_size()
        stop_side = _exit_side(position.side)
        sl_limit = round_to_tick(new_stop - tick if position.side == "long" else new_stop + tick, tick)
        self.client.cancel_open_orders()
        self.client.place_order(
            {
                "size": position.lots,
                "side": stop_side,
                "order_type": "limit_order",
                "stop_order_type": "stop_loss_order",
                "stop_price": str(new_stop),
                "limit_price": str(sl_limit),
                "reduce_only": True,
            }
        )
        self.client.place_order(
            {
                "size": position.lots,
                "side": stop_side,
                "order_type": "limit_order",
                "limit_price": str(position.take_profit_price),
                "reduce_only": True,
            }
        )

    def flatten(self) -> None:
        if self.dry_run:
            logger.info("DRY RUN flatten skipped")
            return
        self.client.cancel_open_orders()
        self.client.close_position_market()

    def _position_from_plan(self, plan: TradePlan, entry_order_id: int | None) -> OpenPosition:
        return OpenPosition(
            side=plan.side,
            entry_price=plan.entry_price,
            lots=plan.lots,
            stop_price=plan.stop_price,
            take_profit_price=plan.take_profit_price,
            profit_lock_price=plan.profit_lock_price,
            max_profit_price=plan.max_profit_price,
            contract_eth=plan.contract_eth,
            entry_ts=utc_now().isoformat(),
            entry_order_id=entry_order_id,
        )
