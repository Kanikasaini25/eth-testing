from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.liquidity import FIXED_ENTRY_LOTS, PARTIAL_EXIT_LOTS, RUNNER_LOTS
from src.config import LIVE_STATE_DIR, STRATEGIES_DIR, ensure_data_dirs
from src.delta_data import DeltaExchangeClient
from src.delta_trading import DeltaTradingClient
from src.email_notify import (
    send_entry_signal_email,
    send_partial_exit_email,
    send_runner_exit_email,
    send_stop_loss_email,
    send_take_profit_email,
)
from src.m15_liquidity import (
    M1_SECONDS,
    M15_SECONDS,
    GrabState,
    SwingPoint,
    closed_bars,
    current_swing_levels,
    find_swing_points,
    grab_from_session_fields,
    process_m15_bar,
)
from src.rule_extractor import TradingRule, rules_from_json
from src.risk import fill_risk_allowed, lots_for_risk, reached_one_r
from src.trade_filters import (
    entry_reward_points,
    m15_trend,
    trend_allows,
)

STOP_TICK_SIZE = 0.05


def _normalize_pending_signal(pending: dict | None) -> dict | None:
    """Drop legacy pending signals saved before the close field was added."""
    if not pending:
        return None
    if "close" not in pending:
        return None
    return pending


@dataclass
class LivePositionState:
    side: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    entry_line: str
    entry_ts: str
    partial_taken: bool = False
    runner_open: bool = False
    best_price: float = 0.0
    entry_lots: int = FIXED_ENTRY_LOTS
    partial_lots: int = PARTIAL_EXIT_LOTS
    runner_lots: int = RUNNER_LOTS
    original_stop: float = 0.0


def _from_dict(cls, data: dict):
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class LiveSessionState:
    day: str = ""
    touched_upper: bool = False
    touched_lower: bool = False
    pending_red: dict[str, float] | None = None
    pending_green: dict[str, float] | None = None
    trades_in_sequence: int = 0
    full_sl_count: int = 0
    upper_entries_today: int = 0
    lower_entries_today: int = 0
    upper_line_blocked: bool = False
    lower_line_blocked: bool = False
    last_processed_ts: str = ""
    grabbed_side: str | None = None
    grab_level: float | None = None
    grab_ts: str = ""
    grab_swing_ts: str = ""
    used_swing_high_ts: str = ""
    used_swing_low_ts: str = ""
    grab_extreme: float | None = None


@dataclass
class LiveStrategyState:
    enabled: bool = False
    symbol: str = "ETHUSD"
    session: LiveSessionState = field(default_factory=LiveSessionState)
    position: LivePositionState | None = None
    upper_level: float | None = None
    lower_level: float | None = None
    logs: list[str] = field(default_factory=list)


@dataclass
class LiveTickResult:
    success: bool
    actions: list[str] = field(default_factory=list)
    mark_price: float | None = None
    upper_level: float | None = None
    lower_level: float | None = None
    exchange_position: int = 0
    in_position: bool = False
    error: str = ""


def default_rules_path() -> Path:
    return STRATEGIES_DIR / "wI9b968AvW8_rules.json"


def load_liquidity_rule(path: Path | None = None) -> TradingRule:
    rules_path = path or default_rules_path()
    if not rules_path.exists():
        raise FileNotFoundError(f"Strategy rules not found: {rules_path}")
    rules = rules_from_json(rules_path.read_text(encoding="utf-8"))
    for rule in rules:
        if rule.strategy_type in {"liquidity", "m15_liquidity_grab"}:
            return rule
    raise ValueError(f"No liquidity strategy in {rules_path}")


class LiveLiquidityRunner:
    """Run 15-minute liquidity grab + 1-minute confirmation on Delta."""

    def __init__(
        self,
        *,
        trading_client: DeltaTradingClient | None = None,
        data_client: DeltaExchangeClient | None = None,
        rule: TradingRule | None = None,
        rules_path: Path | None = None,
        state_path: Path | None = None,
        symbol: str | None = None,
        base_url: str | None = None,
    ) -> None:
        ensure_data_dirs()
        self.trading = trading_client or DeltaTradingClient(base_url=base_url)
        self.base_url = self.trading.base_url
        self.symbol = symbol or self.trading.symbol
        self.data = data_client or DeltaExchangeClient(base_url=self.base_url)
        self.rule = rule or load_liquidity_rule(rules_path)
        self.state_path = state_path or LIVE_STATE_DIR / f"{self.symbol}_live_state.json"
        self.state = self._load_state()

    def _load_state(self) -> LiveStrategyState:
        if not self.state_path.exists():
            return LiveStrategyState(symbol=self.symbol)
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        session_raw = raw.pop("session", {})
        is_legacy = "grabbed_side" not in session_raw
        session = _from_dict(LiveSessionState, session_raw)
        if is_legacy:
            session.pending_red = None
            session.pending_green = None
            session.last_processed_ts = ""
            session.touched_upper = False
            session.touched_lower = False
        else:
            session.pending_red = _normalize_pending_signal(session.pending_red)
            session.pending_green = _normalize_pending_signal(session.pending_green)
        position_raw = raw.pop("position", None)
        position = _from_dict(LivePositionState, position_raw) if position_raw else None
        return _from_dict(LiveStrategyState, {**raw, "session": session, "position": position})

    def _save_state(self) -> None:
        payload = asdict(self.state)
        self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _log(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"[{stamp}] {message}"
        self.state.logs.append(entry)
        self.state.logs = self.state.logs[-100:]

    def _send_email(self, result) -> None:
        if result.success:
            self._log(f"Email sent: {result.message}")
        elif result.message and "disabled" not in result.message.lower():
            self._log(f"Email failed: {result.message}")

    def _params(self) -> dict[str, Any]:
        return self.rule.parameters

    def _reset_session_if_new_day(self, day: str) -> None:
        session = self.state.session
        if session.day == day:
            return
        session.day = day
        session.trades_in_sequence = 0
        session.full_sl_count = 0
        session.upper_entries_today = 0
        session.lower_entries_today = 0
        session.upper_line_blocked = False
        session.lower_line_blocked = False

    def _fetch_market_data(self) -> tuple[list[dict], list[dict]]:
        m15_rows = self.data.fetch_historical_ohlcv(
            symbol=self.symbol,
            resolution="15m",
            days=int(self._params().get("swing_lookback_days", 5)),
        )
        m1_rows = self.data.fetch_historical_ohlcv(
            symbol=self.symbol,
            resolution="1m",
            days=2,
        )
        return m15_rows, m1_rows

    def _now_epoch(self) -> float:
        return datetime.now(timezone.utc).timestamp()

    def _grab_state(self) -> GrabState:
        session = self.state.session
        return grab_from_session_fields(
            grabbed_side=session.grabbed_side,
            grab_level=session.grab_level,
            grab_ts=session.grab_ts,
            grab_swing_ts=session.grab_swing_ts,
            pending_green=session.pending_green,
            pending_red=session.pending_red,
            used_swing_high_ts=session.used_swing_high_ts,
            used_swing_low_ts=session.used_swing_low_ts,
            grab_extreme=session.grab_extreme,
        )

    def _apply_grab_state(self, grab: GrabState) -> None:
        session = self.state.session
        session.grabbed_side = grab.grabbed_side
        session.grab_level = grab.grab_level
        session.grab_ts = grab.grab_ts
        session.grab_swing_ts = grab.grab_swing_ts
        session.pending_green = grab.pending_green
        session.pending_red = grab.pending_red
        session.used_swing_high_ts = grab.used_swing_high_ts
        session.used_swing_low_ts = grab.used_swing_low_ts
        session.grab_extreme = grab.grab_extreme
        session.touched_lower = grab.grabbed_side == "down"
        session.touched_upper = grab.grabbed_side == "up"

    def _new_closed_bars(self, rows: list[dict]) -> list[dict]:
        last_ts = self.state.session.last_processed_ts
        if not last_ts:
            return rows
        return [row for row in rows if row["timestamp"] > last_ts]

    def _order_side(self, side: str) -> str:
        return "buy" if side == "long" else "sell"

    def _exit_side(self, side: str) -> str:
        return "sell" if side == "long" else "buy"

    def _replace_runner_stop(
        self,
        position: LivePositionState,
        stop_price: float,
        mark_price: float | None = None,
    ) -> None:
        """Cancel old stops and place one reduce-only runner stop (or market exit if breached)."""
        exit_side = self._exit_side(position.side)
        mark = mark_price if mark_price is not None else self.trading.get_mark_price(self.symbol)

        self.trading.cancel_open_orders(symbol=self.symbol)
        if self.trading.stop_would_trigger_immediately(exit_side, stop_price, mark, symbol=self.symbol):
            self.trading.place_market_order(
                size=position.runner_lots,
                side=exit_side,
                symbol=self.symbol,
                reduce_only=True,
            )
            self.state.position = None
            self._log(f"Runner stop breached @ {mark:.2f} — closed {position.runner_lots} lots at market")
            return

        try:
            self.trading.place_stop_order(
                size=position.runner_lots,
                side=exit_side,
                stop_price=stop_price,
                symbol=self.symbol,
                reduce_only=True,
                mark_price=mark,
            )
        except Exception as exc:
            if "immediate_execution_stop_order" not in str(exc).lower():
                raise
            self.trading.place_market_order(
                size=position.runner_lots,
                side=exit_side,
                symbol=self.symbol,
                reduce_only=True,
            )
            self.state.position = None
            self._log(f"Runner stop rejected @ {mark:.2f} — closed {position.runner_lots} lots at market")
            return

        position.stop_loss = stop_price

    def _maybe_trail_runner_stop(
        self,
        position: LivePositionState,
        mark_price: float,
        trailing_points: float,
    ) -> bool:
        """Update runner stop only when it moves by at least one tick. Returns True if updated."""
        if not (position.partial_taken and position.runner_open):
            return False

        if position.side == "long":
            position.best_price = max(position.best_price, mark_price)
            new_stop = max(position.entry_price, position.best_price - trailing_points)
            if new_stop <= position.stop_loss + STOP_TICK_SIZE:
                return False
        else:
            position.best_price = min(position.best_price or mark_price, mark_price)
            new_stop = min(position.entry_price, position.best_price + trailing_points)
            if new_stop >= position.stop_loss - STOP_TICK_SIZE:
                return False

        self._replace_runner_stop(position, new_stop, mark_price)
        return True

    def _expected_exchange_size(self) -> int:
        """Signed lot size the exchange should show for the tracked position."""
        position = self.state.position
        if position is None:
            return 0
        if position.partial_taken and position.runner_open:
            lots = position.runner_lots
        else:
            lots = position.entry_lots
        return -lots if position.side == "short" else lots

    def _adjust_entry_stop_price(self, side: str, stop_loss: float, mark: float) -> float:
        tick = self.trading.get_product_tick_size(self.symbol)
        if side == "short" and stop_loss <= mark + tick:
            return mark + max(tick, 3.0)
        if side == "long" and stop_loss >= mark - tick:
            return mark - max(tick, 3.0)
        return stop_loss

    def _place_entry_stop(
        self,
        side: str,
        stop_side: str,
        stop_loss: float,
        entry_lots: int,
    ) -> float:
        mark = self.trading.get_mark_price(self.symbol)
        adjusted = self._adjust_entry_stop_price(side, stop_loss, mark)
        self.trading.place_stop_order(
            size=entry_lots,
            side=stop_side,
            stop_price=adjusted,
            symbol=self.symbol,
            reduce_only=True,
            mark_price=mark,
        )
        return adjusted

    def _place_take_profit_limit(self, side: str, target_price: float, lots: int) -> None:
        self.trading.place_limit_order(
            size=lots,
            side=self._exit_side(side),
            limit_price=target_price,
            symbol=self.symbol,
            reduce_only=True,
        )

    def _targets_from_fill(
        self,
        side: str,
        fill_price: float,
        stop_loss: float,
        fallback_target: float,
    ) -> tuple[float, float]:
        min_tp = float(self._params().get("partial_target_points", 15))
        reward_r = float(self._params().get("reward_r_multiple", 2.0))
        points = entry_reward_points(abs(fill_price - stop_loss), min_tp, reward_r)
        if points <= 0:
            return fallback_target, fallback_target
        target = fill_price + points if side == "long" else fill_price - points
        return target, target

    def _execute_entry(
        self,
        side: str,
        entry_price: float,
        stop_loss: float,
        target_1: float,
        target_2: float,
        entry_line: str,
        entry_ts: str,
    ) -> list[str]:
        params = self._params()
        entry_lots = int(params.get("position_lots", FIXED_ENTRY_LOTS))
        if bool(params.get("use_risk_sizing", True)):
            sized = lots_for_risk(
                float(params.get("starting_wallet_usd", 10000)),
                abs(entry_price - stop_loss),
                risk_pct=float(params.get("risk_pct_per_trade", 1.0)),
                min_lots=int(params.get("min_lots", 1)),
                max_lots=int(params.get("position_lots", 20)),
                use_risk_sizing=True,
                fallback_lots=entry_lots,
            )
            if sized < 1:
                return [f"Entry skipped: 1% risk is smaller than 1 lot at this stop"]
            entry_lots = sized
        runner_lots = min(int(params.get("runner_lots", 0)), entry_lots)
        partial_lots = entry_lots - runner_lots
        order_side = self._order_side(side)
        stop_side = self._exit_side(side)

        exchange_size = self.trading.get_open_position_size(self.symbol)
        if exchange_size != 0:
            msg = (
                f"Entry blocked: exchange has {exchange_size} lots but bot is flat — "
                "flatten on Delta first"
            )
            self._log(msg)
            return [msg]

        self.trading.place_market_order(size=entry_lots, side=order_side, symbol=self.symbol)
        fill_price = self.trading.get_mark_price(self.symbol) or entry_price
        target_1, target_2 = self._targets_from_fill(side, fill_price, stop_loss, target_1)
        try:
            placed_sl = self._place_entry_stop(side, stop_side, stop_loss, entry_lots)
        except Exception as exc:
            rollback_msg = f"Stop order failed — rolling back {entry_lots} lots"
            self._log(rollback_msg)
            try:
                self.trading.place_market_order(
                    size=entry_lots,
                    side=stop_side,
                    symbol=self.symbol,
                    reduce_only=True,
                )
                detail = f"Entry aborted: {exc}"
            except Exception as rollback_exc:
                detail = (
                    f"CRITICAL: {entry_lots} lots open on exchange, stop and rollback failed: "
                    f"{rollback_exc}"
                )
            self._log(detail)
            return [rollback_msg, detail]

        try:
            self._place_take_profit_limit(side, target_1, entry_lots)
        except Exception as exc:  # noqa: BLE001
            self._log(f"Take-profit limit failed, managing in software: {exc}")

        self.state.position = LivePositionState(
            side=side,
            entry_price=fill_price,
            stop_loss=placed_sl,
            target_1=target_1,
            target_2=target_2,
            entry_line=entry_line,
            entry_ts=entry_ts,
            entry_lots=entry_lots,
            partial_lots=partial_lots,
            runner_lots=runner_lots,
            original_stop=placed_sl,
        )
        action = (
            f"ENTER {side.upper()} {entry_lots} lots @ ~{fill_price:.2f}, "
            f"SL {placed_sl:.2f}, TP {target_1:.2f}"
        )
        self._log(action)

        email_result = send_entry_signal_email(
            symbol=self.symbol,
            side=side,
            entry_price=fill_price,
            stop_loss=placed_sl,
            target_1=target_1,
            target_2=target_2,
            entry_lots=entry_lots,
            partial_lots=partial_lots,
            runner_lots=runner_lots,
            entry_line=entry_line,
            entry_ts=entry_ts,
            upper_level=self.state.upper_level,
            lower_level=self.state.lower_level,
        )
        self._send_email(email_result)

        return [action]

    def _execute_take_profit(self, position: LivePositionState, exit_price: float) -> list[str]:
        lots = position.runner_lots if position.partial_taken else position.entry_lots
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.close_position_at_market(symbol=self.symbol)
        self.state.position = None
        action = f"TAKE PROFIT {lots} lots @ ~{exit_price:.2f}"
        self._log(action)
        self._send_email(
            send_take_profit_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=exit_price,
                lots=lots,
                target=position.target_1,
            )
        )
        return [action]

    def _execute_partial_exit(self, position: LivePositionState, exit_price: float) -> list[str]:
        exit_side = self._exit_side(position.side)
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.place_market_order(
            size=position.partial_lots,
            side=exit_side,
            symbol=self.symbol,
            reduce_only=True,
        )

        params = self._params()
        trailing_points = float(params.get("trailing_stop_points", 3.0))
        use_trailing = bool(params.get("use_trailing_stop_after_partial", True))
        if use_trailing:
            if position.side == "long":
                position.best_price = max(position.target_1, exit_price)
                position.stop_loss = max(position.entry_price, position.best_price - trailing_points)
            else:
                position.best_price = min(position.target_1, exit_price)
                position.stop_loss = min(position.entry_price, position.best_price + trailing_points)
        else:
            position.stop_loss = position.entry_price

        self._replace_runner_stop(position, position.stop_loss, exit_price)
        position.partial_taken = True
        position.runner_open = True

        action = (
            f"PARTIAL EXIT {position.partial_lots} lots @ ~{exit_price:.2f}, "
            f"runner SL {position.stop_loss:.2f}"
        )
        self._log(action)
        self._send_email(
            send_partial_exit_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=exit_price,
                partial_lots=position.partial_lots,
                runner_lots=position.runner_lots,
                runner_stop_loss=position.stop_loss,
                target_1=position.target_1,
            )
        )
        return [action]

    def _execute_runner_exit(
        self,
        position: LivePositionState,
        exit_price: float,
        reason: str,
    ) -> list[str]:
        exit_side = self._exit_side(position.side)
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.place_market_order(
            size=position.runner_lots,
            side=exit_side,
            symbol=self.symbol,
            reduce_only=True,
        )
        self.state.position = None
        action = f"RUNNER EXIT ({reason}) {position.runner_lots} lots @ ~{exit_price:.2f}"
        self._log(action)
        if reason in {"trailing_stop", "breakeven_stop", "stop_loss"}:
            self._send_email(
                send_stop_loss_email(
                    symbol=self.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    lots=position.runner_lots,
                    stop_loss=position.stop_loss,
                    exit_type=reason,
                    partial_was_taken=True,
                )
            )
        else:
            self._send_email(
                send_runner_exit_email(
                    symbol=self.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=exit_price,
                    runner_lots=position.runner_lots,
                    reason=reason,
                )
            )
        return [action]

    def _execute_full_stop(self, position: LivePositionState, exit_price: float) -> list[str]:
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.close_position_at_market(symbol=self.symbol)
        session = self.state.session
        if not position.partial_taken:
            session.full_sl_count += 1
            if position.entry_line == "upper":
                session.upper_line_blocked = True
            elif position.entry_line == "lower":
                session.lower_line_blocked = True
        self.state.position = None
        action = f"STOP LOSS {position.entry_lots} lots @ ~{exit_price:.2f}"
        self._log(action)
        self._send_email(
            send_stop_loss_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=exit_price,
                lots=position.entry_lots,
                stop_loss=position.stop_loss,
                exit_type="stop_loss",
                partial_was_taken=position.partial_taken,
            )
        )
        return [action]

    def _is_take_profit_close(self, position: LivePositionState, mark_price: float) -> bool:
        buffer = 1.0
        if position.side == "long":
            return mark_price >= position.target_1 - buffer
        return mark_price <= position.target_1 + buffer

    def _sync_exchange_flat(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []

        self.trading.cancel_open_orders(symbol=self.symbol)
        lots = position.runner_lots if position.partial_taken else position.entry_lots
        if self._is_take_profit_close(position, mark_price):
            self.state.position = None
            action = f"TAKE PROFIT {lots} lots @ ~{mark_price:.2f}"
            self._log(action)
            self._send_email(
                send_take_profit_email(
                    symbol=self.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=mark_price,
                    lots=lots,
                    target=position.target_1,
                )
            )
            return [action]

        was_partial = position.partial_taken
        session = self.state.session
        if not was_partial:
            session.full_sl_count += 1
            if position.entry_line == "upper":
                session.upper_line_blocked = True
            elif position.entry_line == "lower":
                session.lower_line_blocked = True
        self.state.position = None
        action = f"Position closed on exchange @ ~{mark_price:.2f}"
        self._log(action)
        self._send_email(
            send_stop_loss_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=mark_price,
                lots=lots,
                stop_loss=position.stop_loss,
                exit_type="exchange_stop",
                partial_was_taken=was_partial,
            )
        )
        return [action]

    def _maybe_move_full_stop_to_breakeven(
        self,
        position: LivePositionState,
        mark_price: float,
    ) -> str | None:
        original = position.original_stop if position.original_stop > 0 else position.stop_loss
        if abs(position.stop_loss - position.entry_price) <= STOP_TICK_SIZE:
            return None
        if not reached_one_r(
            position.side,
            position.entry_price,
            original,
            mark_price,
            mark_price,
        ):
            return None
        self.trading.cancel_open_orders(symbol=self.symbol)
        placed = self._place_entry_stop(
            position.side,
            self._exit_side(position.side),
            position.entry_price,
            position.entry_lots,
        )
        try:
            self._place_take_profit_limit(position.side, position.target_1, position.entry_lots)
        except Exception as exc:
            self._log(f"Take-profit limit failed after breakeven, managing in software: {exc}")
        position.stop_loss = placed
        return f"Moved stop to breakeven @ {placed:.2f}"

    def _manage_open_position(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []

        params = self._params()
        trailing_points = float(params.get("trailing_stop_points", 3.0))
        use_trailing = bool(params.get("use_trailing_stop_after_partial", False))
        full_take_profit = position.runner_lots <= 0
        actions: list[str] = []

        exchange_size = self.trading.get_open_position_size(self.symbol)
        if exchange_size == 0:
            return self._sync_exchange_flat(mark_price)

        expected = self._expected_exchange_size()
        if exchange_size != expected:
            msg = (
                f"Position mismatch: exchange {exchange_size} lots vs tracked {expected} — "
                "flatten on Delta and reset state before continuing"
            )
            self._log(msg)
            return [msg]

        hit_tp = (
            mark_price >= position.target_1
            if position.side == "long"
            else mark_price <= position.target_1
        )
        hit_sl = (
            mark_price <= position.stop_loss
            if position.side == "long"
            else mark_price >= position.stop_loss
        )

        if full_take_profit:
            if hit_tp:
                return self._execute_take_profit(position, mark_price)
            if hit_sl:
                return self._execute_full_stop(position, mark_price)
            if bool(params.get("move_stop_to_breakeven", True)):
                moved = self._maybe_move_full_stop_to_breakeven(position, mark_price)
                if moved:
                    actions.append(moved)
            return actions

        if use_trailing:
            self._maybe_trail_runner_stop(position, mark_price, trailing_points)

        if not position.partial_taken and hit_tp:
            actions.extend(self._execute_partial_exit(position, mark_price))
        elif position.partial_taken and position.runner_open and (
            mark_price >= position.target_2 if position.side == "long" else mark_price <= position.target_2
        ):
            actions.extend(self._execute_runner_exit(position, mark_price, "swing_target"))
        elif not position.partial_taken and hit_sl:
            actions.extend(self._execute_full_stop(position, mark_price))
        elif position.partial_taken and position.runner_open and hit_sl:
            reason = (
                "breakeven_stop"
                if position.stop_loss == position.entry_price
                else "trailing_stop"
            )
            actions.extend(self._execute_runner_exit(position, mark_price, reason))

        return actions

    def _session_limits_reached(self) -> bool:
        params = self._params()
        session = self.state.session
        max_trades = int(params.get("max_trades_per_sequence", 0))
        max_full_sl = int(params.get("max_full_stop_losses_per_session", 0))
        if max_full_sl > 0 and session.full_sl_count >= max_full_sl:
            return True
        if max_trades > 0 and session.trades_in_sequence >= max_trades:
            return True
        return False

    def _process_entry_bar(
        self,
        row: dict,
        swings: list[SwingPoint],
        closed_m15: list[dict] | None = None,
    ) -> list[str]:
        if self.state.position is not None or self._session_limits_reached():
            return []

        params = self._params()
        grab = self._grab_state()
        max_sl = float(params.get("max_stop_loss_points", 10.0))
        signal = process_m15_bar(
            row,
            swings,
            grab,
            target_points=float(params.get("partial_target_points", 15)),
            confirmation_window_bars=int(params.get("confirmation_window_bars", 8)),
            require_close_beyond=bool(params.get("require_close_beyond", True)),
            stop_loss_mode=str(params.get("stop_loss_mode", "first_confirmation_candle")),
            min_sl_points=float(params.get("min_stop_loss_points", 5.0)),
            max_sl_points=max_sl,
            min_reward_to_risk=float(params.get("min_reward_to_risk", 1.5)),
            min_sweep_points=float(params.get("min_sweep_points", 3.0)),
            reward_r=float(params.get("reward_r_multiple", 2.0)),
            use_session_filter=bool(params.get("use_session_filter", True)),
            session_start_hour_utc=int(params.get("session_start_hour_utc", 8)),
            session_end_hour_utc=int(params.get("session_end_hour_utc", 20)),
        )
        self._apply_grab_state(grab)
        if signal is None:
            return []

        if bool(params.get("use_trend_filter", True)):
            lookback = int(params.get("trend_lookback_bars", 12))
            trend = m15_trend(closed_m15 or [], lookback)
            if not trend_allows(signal.side, trend):
                return [f"Skipped {signal.side}: 15m trend is {trend}"]

        fill = float(row["close"])
        min_tp = float(params.get("partial_target_points", 15))
        reward_r = float(params.get("reward_r_multiple", 2.5))
        min_rr = float(params.get("min_reward_to_risk", 2.0))
        if not fill_risk_allowed(
            fill,
            signal.stop_loss,
            max_sl_points=max_sl,
            min_reward_to_risk=min_rr,
            min_target=min_tp,
            reward_r=reward_r,
        ):
            return [
                f"Skipped {signal.side}: fill stop {abs(fill - signal.stop_loss):.2f} pts "
                f"fails 5–10 point / {min_rr:.1f}R check"
            ]

        session = self.state.session
        session.trades_in_sequence += 1
        if signal.side == "long":
            session.lower_entries_today += 1
        else:
            session.upper_entries_today += 1
        return self._execute_entry(
            signal.side,
            fill,
            signal.stop_loss,
            signal.target,
            signal.target,
            signal.entry_line,
            row["timestamp"],
        )

    def _warmup_if_needed(self, m1_closed: list[dict]) -> str | None:
        if self.state.session.last_processed_ts or not m1_closed:
            return None
        self.state.session.last_processed_ts = m1_closed[-1]["timestamp"]
        return "Warmed up — waiting for next 1m bar"

    def tick(self, *, dry_run: bool = False) -> LiveTickResult:
        if not self.trading.is_configured:
            return LiveTickResult(success=False, error="Delta API credentials not configured")

        if not self.state.enabled and not dry_run:
            return LiveTickResult(
                success=True,
                actions=["Strategy disabled — turn on 'Strategy enabled' to place live orders"],
                in_position=self.state.position is not None,
            )

        try:
            m15_rows, m1_rows = self._fetch_market_data()
            mark_price = self.trading.get_mark_price(self.symbol)
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._reset_session_if_new_day(day)

            now_epoch = self._now_epoch()
            m15_closed = closed_bars(m15_rows, M15_SECONDS, now_epoch)
            m1_closed = closed_bars(m1_rows, M1_SECONDS, now_epoch)
            fractal = int(self._params().get("swing_fractal_bars", 2))
            swings = find_swing_points(m15_closed, left=fractal, right=fractal)
            as_of = (
                m1_closed[-1]["timestamp"]
                if m1_closed
                else datetime.now(timezone.utc).isoformat()
            )
            upper, lower = current_swing_levels(swings, as_of)
            self.state.upper_level = upper
            self.state.lower_level = lower

            actions: list[str] = []

            if self.state.position is not None:
                if dry_run:
                    actions.append(f"[DRY RUN] Manage position @ {mark_price:.2f}")
                else:
                    actions.extend(self._manage_open_position(mark_price))
            else:
                exchange_size = self.trading.get_open_position_size(self.symbol)
                if exchange_size != 0:
                    actions.append(
                        f"Orphan position on exchange: {exchange_size} lots — "
                        "bot is flat; close on Delta before new entries"
                    )
                else:
                    warmup = self._warmup_if_needed(m1_closed)
                    if warmup:
                        actions.append(warmup)
                    else:
                        new_bars = self._new_closed_bars(m1_closed)
                        processed = 0
                        for row in new_bars:
                            if not dry_run:
                                actions.extend(self._process_entry_bar(row, swings, m15_closed))
                            processed += 1
                            self.state.session.last_processed_ts = row["timestamp"]
                            if self.state.position is not None:
                                break

                        if dry_run and processed:
                            actions.append(
                                f"[DRY RUN] Scanned {processed} closed 1m bars — no orders placed"
                            )
                        elif processed and not actions:
                            grab_note = ""
                            if self.state.session.grabbed_side:
                                grab_note = f" ({self.state.session.grabbed_side}side grab active)"
                            actions.append(
                                f"Scanned {processed} new 1m bars — no entry signal{grab_note}"
                            )

            exchange_position = self.trading.get_open_position_size(self.symbol)
            self._save_state()
            return LiveTickResult(
                success=True,
                actions=actions or ["No action this tick"],
                mark_price=mark_price,
                upper_level=upper,
                lower_level=lower,
                exchange_position=exchange_position,
                in_position=self.state.position is not None,
            )
        except Exception as exc:  # noqa: BLE001
            return LiveTickResult(success=False, error=str(exc))

    def set_enabled(self, enabled: bool) -> None:
        self.state.enabled = enabled
        self._log("Strategy ENABLED" if enabled else "Strategy DISABLED")
        self._save_state()
