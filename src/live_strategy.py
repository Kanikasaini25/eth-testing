from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.backtest import (
    FIXED_ENTRY_LOTS,
    PARTIAL_EXIT_LOTS,
    RUNNER_LOTS,
    _daily_liquidity_levels,
    _liquidity_sweep_at_lower,
    _liquidity_sweep_at_upper,
    _liquidity_targets,
    _liquidity_timing_ok,
    _passes_liquidity_entry_filters,
    _signal_body_ratio,
)
from src.config import LIVE_STATE_DIR, PROJECT_DIR, STRATEGIES_DIR, ensure_data_dirs, get_env
from src.delta_data import DeltaExchangeClient
from src.delta_trading import DeltaTradingClient
from src.email_notify import (
    send_entry_signal_email,
    send_partial_exit_email,
    send_runner_exit_email,
    send_stop_loss_email,
)
from src.rule_extractor import TradingRule, load_rules

STOP_TICK_SIZE = 0.05


def _normalize_pending_signal(pending: dict | None) -> dict | None:
    """Drop legacy pending signals saved before the close field was added."""
    if not pending:
        return None
    if "close" not in pending:
        return None
    return pending


def _pending_signal_close(pending: dict, side: str) -> float:
    if "close" in pending:
        return float(pending["close"])
    return float(pending["low"] if side == "short" else pending["high"])


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


@dataclass
class LiveSessionState:
    day: str = ""
    touched_upper: bool = False
    touched_lower: bool = False
    first_upper_ts: str = ""
    first_lower_ts: str = ""
    pending_red: dict[str, float] | None = None
    pending_green: dict[str, float] | None = None
    trades_in_sequence: int = 0
    full_sl_count: int = 0
    upper_entries_today: int = 0
    lower_entries_today: int = 0
    upper_line_blocked: bool = False
    lower_line_blocked: bool = False
    last_processed_ts: str = ""


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
    configured = get_env("STRATEGY_RULES")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            path = PROJECT_DIR / path
        return path
    return STRATEGIES_DIR / "lqdty_liquidity.json"


def load_liquidity_rule(path: Path | None = None) -> TradingRule:
    rules_path = path or default_rules_path()
    rules = load_rules(rules_path)
    for rule in rules:
        if rule.strategy_type == "liquidity":
            return rule
    raise ValueError(f"No liquidity strategy in {rules_path}")


class LiveLiquidityRunner:
    """Run LQDTY liquidity strategy on Delta demo/live account."""

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
        session = LiveSessionState(**raw.pop("session", {}))
        session.pending_red = _normalize_pending_signal(session.pending_red)
        session.pending_green = _normalize_pending_signal(session.pending_green)
        position_raw = raw.pop("position", None)
        position = LivePositionState(**position_raw) if position_raw else None
        return LiveStrategyState(session=session, position=position, **raw)

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
        session.touched_upper = False
        session.touched_lower = False
        session.first_upper_ts = ""
        session.first_lower_ts = ""
        session.pending_red = None
        session.pending_green = None
        session.trades_in_sequence = 0
        session.full_sl_count = 0
        session.upper_entries_today = 0
        session.lower_entries_today = 0
        session.upper_line_blocked = False
        session.lower_line_blocked = False
        session.last_processed_ts = ""

    def _today_levels(
        self,
        daily_rows: list[dict],
        day: str,
    ) -> tuple[float | None, float | None]:
        levels = _daily_liquidity_levels(daily_rows)
        day_levels = levels.get(day)
        if not day_levels:
            return None, None
        return day_levels["upper"], day_levels["lower"]

    def _fetch_market_data(self) -> tuple[list[dict], list[dict]]:
        daily_rows = self.data.fetch_historical_ohlcv(
            symbol=self.symbol,
            resolution="1d",
            days=int(self._params().get("swing_lookback_days", 20)) + 5,
        )
        intraday_rows = self.data.fetch_historical_ohlcv(
            symbol=self.symbol,
            resolution="1m",
            days=2,
        )
        return daily_rows, intraday_rows

    def _closed_bars_today(self, intraday_rows: list[dict], day: str) -> list[dict]:
        now = datetime.now(timezone.utc)
        today_bars = [row for row in intraday_rows if row["timestamp"][:10] == day]
        closed: list[dict] = []
        for row in today_bars:
            bar_time = datetime.fromisoformat(row["timestamp"])
            bar_end = bar_time.timestamp() + 60
            if bar_end <= now.timestamp():
                closed.append(row)
        return closed

    def _new_closed_bars(self, closed_bars: list[dict]) -> list[dict]:
        last_ts = self.state.session.last_processed_ts
        if not last_ts:
            return closed_bars
        return [row for row in closed_bars if row["timestamp"] > last_ts]

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
        partial_lots = int(params.get("partial_exit_lots", entry_lots * PARTIAL_EXIT_LOTS // FIXED_ENTRY_LOTS))
        runner_lots = int(params.get("runner_lots", entry_lots - partial_lots))
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

        self.state.position = LivePositionState(
            side=side,
            entry_price=entry_price,
            stop_loss=placed_sl,
            target_1=target_1,
            target_2=target_2,
            entry_line=entry_line,
            entry_ts=entry_ts,
            entry_lots=entry_lots,
            partial_lots=partial_lots,
            runner_lots=runner_lots,
        )
        action = f"ENTER {side.upper()} {entry_lots} lots @ ~{entry_price:.2f}, SL {placed_sl:.2f}"
        self._log(action)

        email_result = send_entry_signal_email(
            symbol=self.symbol,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
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

    def _sync_exchange_flat(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []

        was_partial = position.partial_taken
        stop_loss = position.stop_loss
        entry_price = position.entry_price
        side = position.side
        lots = position.runner_lots if was_partial else position.entry_lots
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
                side=side,
                entry_price=entry_price,
                exit_price=mark_price,
                lots=lots,
                stop_loss=stop_loss,
                exit_type="exchange_stop",
                partial_was_taken=was_partial,
            )
        )
        return [action]

    def _manage_open_position(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []

        params = self._params()
        trailing_points = float(params.get("trailing_stop_points", 3.0))
        use_trailing = bool(params.get("use_trailing_stop_after_partial", True))
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

        if position.side == "long":
            if use_trailing:
                self._maybe_trail_runner_stop(position, mark_price, trailing_points)

            if not position.partial_taken and mark_price >= position.target_1:
                actions.extend(self._execute_partial_exit(position, mark_price))
            elif position.partial_taken and position.runner_open and mark_price >= position.target_2:
                actions.extend(self._execute_runner_exit(position, mark_price, "swing_target"))
            elif not position.partial_taken and mark_price <= position.stop_loss:
                actions.extend(self._execute_full_stop(position, mark_price))
            elif position.partial_taken and position.runner_open and mark_price <= position.stop_loss:
                reason = (
                    "breakeven_stop"
                    if position.stop_loss == position.entry_price
                    else "trailing_stop"
                )
                actions.extend(self._execute_runner_exit(position, mark_price, reason))

        elif position.side == "short":
            if use_trailing:
                self._maybe_trail_runner_stop(position, mark_price, trailing_points)

            if not position.partial_taken and mark_price <= position.target_1:
                actions.extend(self._execute_partial_exit(position, mark_price))
            elif position.partial_taken and position.runner_open and mark_price <= position.target_2:
                actions.extend(self._execute_runner_exit(position, mark_price, "swing_target"))
            elif not position.partial_taken and mark_price >= position.stop_loss:
                actions.extend(self._execute_full_stop(position, mark_price))
            elif position.partial_taken and position.runner_open and mark_price >= position.stop_loss:
                reason = (
                    "breakeven_stop"
                    if position.stop_loss == position.entry_price
                    else "trailing_stop"
                )
                actions.extend(self._execute_runner_exit(position, mark_price, reason))

        return actions

    def _process_entry_bar(
        self,
        row: dict,
        prev_row: dict | None,
        daily_rows: list[dict],
        upper: float,
        lower: float,
    ) -> list[str]:
        if self.state.position is not None:
            return []

        params = self._params()
        session = self.state.session
        max_trades = int(params.get("max_trades_per_sequence", 3))
        max_full_sl = int(params.get("max_full_stop_losses_per_session", 2))
        max_entries_per_line = int(params.get("max_entries_per_liquidity_line_per_day", 1))
        partial_target_points = float(params.get("partial_target_points", 15))
        use_swing_target_for_partial = bool(params.get("use_swing_target_for_partial", False))
        min_sl_points = float(params.get("min_stop_loss_points", 4.0))
        max_sl_points = float(params.get("max_stop_loss_points", 7.0))
        min_reward_to_risk = float(params.get("min_reward_to_risk", 2.5))
        min_signal_body_ratio = float(params.get("min_signal_body_ratio", 0.75))
        min_signal_range_points = float(params.get("min_signal_range_points", 3.5))
        entry_on_next_candle = bool(params.get("entry_on_next_candle", True))
        require_close_beyond_signal = bool(params.get("require_close_beyond_signal", True))
        require_liquidity_sweep = bool(params.get("require_liquidity_sweep", False))
        require_signal_touches_line = bool(params.get("require_signal_touches_line", False))
        max_entry_distance_points = float(params.get("max_entry_distance_from_line_points", 8.0))
        max_minutes_after_touch = float(params.get("max_minutes_after_liquidity_touch", 0.0))
        allow_longs = bool(params.get("allow_longs", True))
        allow_shorts = bool(params.get("allow_shorts", True))
        use_daily_trend_filter = bool(params.get("use_daily_trend_filter", False))
        use_session_filter = bool(params.get("use_session_filter", True))
        session_start_hour_utc = int(params.get("session_start_hour_utc", 8))
        session_end_hour_utc = int(params.get("session_end_hour_utc", 20))
        swing_lookback = int(params.get("swing_lookback_days", 20))
        runner_swing_lookback = int(params.get("runner_swing_lookback_days", 60))
        max_sl_pct = float(params.get("max_stop_loss_pct", 5.0))

        if session.full_sl_count >= max_full_sl or session.trades_in_sequence >= max_trades:
            return []

        timestamp = row["timestamp"]
        day = timestamp[:10]
        open_price = float(row["open"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])

        if high >= upper:
            session.touched_upper = True
            if not session.first_upper_ts:
                session.first_upper_ts = timestamp
        if low <= lower:
            session.touched_lower = True
            if not session.first_lower_ts:
                session.first_lower_ts = timestamp

        if not session.touched_upper and not session.touched_lower:
            return []

        if session.touched_upper and close < open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            sweep_ok = not require_liquidity_sweep or _liquidity_sweep_at_upper(high, close, upper)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or (high - low) >= min_signal_range_points
            touches_line = high >= upper
            timing_ok = _liquidity_timing_ok(
                session.first_upper_ts, timestamp, max_minutes_after_touch
            )
            if body_ok and range_ok and sweep_ok and timing_ok:
                if not require_signal_touches_line or touches_line:
                    session.pending_red = {
                        "high": high,
                        "low": low,
                        "close": close,
                        "index_ts": timestamp,
                    }

        if allow_longs and session.touched_lower and close > open_price:
            body_ratio = _signal_body_ratio(open_price, high, low, close)
            sweep_ok = not require_liquidity_sweep or _liquidity_sweep_at_lower(low, close, lower)
            body_ok = min_signal_body_ratio <= 0 or body_ratio >= min_signal_body_ratio
            range_ok = min_signal_range_points <= 0 or (high - low) >= min_signal_range_points
            touches_line = low <= lower
            timing_ok = _liquidity_timing_ok(
                session.first_lower_ts, timestamp, max_minutes_after_touch
            )
            if body_ok and range_ok and sweep_ok and timing_ok:
                if not require_signal_touches_line or touches_line:
                    session.pending_green = {
                        "high": high,
                        "low": low,
                        "close": close,
                        "index_ts": timestamp,
                    }

        actions: list[str] = []

        pending_red = session.pending_red
        if (
            allow_shorts
            and pending_red
            and (timestamp > pending_red["index_ts"] if entry_on_next_candle else True)
        ):
            if low < pending_red["low"]:
                short_break_ok = close < pending_red["low"] if require_close_beyond_signal else True
                if short_break_ok:
                    if session.upper_line_blocked or session.upper_entries_today >= max_entries_per_line:
                        session.pending_red = None
                    else:
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
                                signal_close=_pending_signal_close(signal, "short"),
                                upper=upper,
                                lower=lower,
                                use_daily_trend_filter=use_daily_trend_filter,
                                use_session_filter=use_session_filter,
                                session_start_hour_utc=session_start_hour_utc,
                                session_end_hour_utc=session_end_hour_utc,
                                require_signal_touches_line=require_signal_touches_line,
                                max_entry_distance_points=max_entry_distance_points,
                                max_minutes_after_touch=max_minutes_after_touch,
                                first_touch_ts=session.first_upper_ts,
                            )
                            and target_1 > 0
                            and entry_price > target_1
                        ):
                            session.trades_in_sequence += 1
                            session.upper_entries_today += 1
                            session.pending_red = None
                            actions.extend(
                                self._execute_entry(
                                    "short",
                                    entry_price,
                                    stop_loss,
                                    target_1,
                                    target_2,
                                    "upper",
                                    timestamp,
                                )
                            )

        pending_green = session.pending_green
        if (
            allow_longs
            and pending_green
            and (timestamp > pending_green["index_ts"] if entry_on_next_candle else True)
        ):
            if high > pending_green["high"]:
                long_break_ok = close > pending_green["high"] if require_close_beyond_signal else True
                if long_break_ok:
                    if session.lower_line_blocked or session.lower_entries_today >= max_entries_per_line:
                        session.pending_green = None
                    else:
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
                                signal_close=_pending_signal_close(signal, "long"),
                                upper=upper,
                                lower=lower,
                                use_daily_trend_filter=use_daily_trend_filter,
                                use_session_filter=use_session_filter,
                                session_start_hour_utc=session_start_hour_utc,
                                session_end_hour_utc=session_end_hour_utc,
                                require_signal_touches_line=require_signal_touches_line,
                                max_entry_distance_points=max_entry_distance_points,
                                max_minutes_after_touch=max_minutes_after_touch,
                                first_touch_ts=session.first_lower_ts,
                            )
                            and target_1 > 0
                            and entry_price < target_1
                        ):
                            session.trades_in_sequence += 1
                            session.lower_entries_today += 1
                            session.pending_green = None
                            actions.extend(
                                self._execute_entry(
                                    "long",
                                    entry_price,
                                    stop_loss,
                                    target_1,
                                    target_2,
                                    "lower",
                                    timestamp,
                                )
                            )

        return actions

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
            daily_rows, intraday_rows = self._fetch_market_data()
            mark_price = self.trading.get_mark_price(self.symbol)
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            self._reset_session_if_new_day(day)

            upper, lower = self._today_levels(daily_rows, day)
            self.state.upper_level = upper
            self.state.lower_level = lower

            if upper is None or lower is None:
                self._save_state()
                return LiveTickResult(
                    success=True,
                    mark_price=mark_price,
                    upper_level=upper,
                    lower_level=lower,
                    exchange_position=self.trading.get_open_position_size(self.symbol),
                    in_position=self.state.position is not None,
                    actions=["Waiting for daily liquidity levels"],
                )

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
                    closed_bars = self._closed_bars_today(intraday_rows, day)
                    new_bars = self._new_closed_bars(closed_bars)
                    bar_index = {row["timestamp"]: idx for idx, row in enumerate(closed_bars)}
                    processed = 0

                    for row in new_bars:
                        prev_row = None
                        idx = bar_index.get(row["timestamp"])
                        if idx is not None and idx > 0:
                            prev_row = closed_bars[idx - 1]
                        if not dry_run:
                            actions.extend(
                                self._process_entry_bar(row, prev_row, daily_rows, upper, lower)
                            )
                        processed += 1
                        self.state.session.last_processed_ts = row["timestamp"]
                        if self.state.position is not None:
                            break

                    if dry_run and processed:
                        actions.append(f"[DRY RUN] Scanned {processed} closed 1m bars — no orders placed")
                    elif processed and not actions:
                        actions.append(f"Scanned {processed} new 1m bars — no entry signal")

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
