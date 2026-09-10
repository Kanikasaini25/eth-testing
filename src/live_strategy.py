"""Live ETH India volume-bias strategy: day volume → 7pm IST pullback entry."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.config import LIVE_STATE_DIR, ensure_data_dirs, get_env
from src.delta_data import RESOLUTION_SECONDS, DeltaExchangeClient
from src.delta_trading import DeltaTradingClient
from src.email_notify import send_entry_signal_email, send_stop_loss_email, send_take_profit_email
from src.eth_volume_strategy import (
    CLOSE_TARGET_PCT,
    DEFAULT_ENTRY_HOUR_IST,
    DEFAULT_ENTRY_RESOLUTION,
    DEFAULT_POSITION_LOTS,
    DEFAULT_PULLBACK_RESOLUTION,
    closed_bars_on_day,
    day_limit_reached,
    decide_open_trade,
    exit_side,
    favorable_move_pct,
    measure_volume_bias,
    now_in_entry_window,
    order_side,
    pullback_and_confirmation,
    pullback_stop_loss,
    signed_points,
    split_session_bars,
    stop_is_valid,
    target_price,
)
from src.live_state import (
    LivePositionState, LiveSessionState, LiveTickResult,
    append_log, env_float, env_int, load_strategy_state, save_strategy_state,
)
from src.timezone import india_today

INDIA_LIVE_DATA_URL = "https://api.india.delta.exchange"


class LiveEthVolumeRunner:
    """Follow India-live ETH volume; place orders on the trade account."""

    def __init__(
        self,
        *,
        trading_client: DeltaTradingClient | None = None,
        data_client: DeltaExchangeClient | None = None,
        state_path: Path | None = None,
        symbol: str | None = None,
        base_url: str | None = None,
        data_base_url: str | None = None,
    ) -> None:
        ensure_data_dirs()
        self.trading = trading_client or DeltaTradingClient(base_url=base_url)
        self.base_url = self.trading.base_url
        self.symbol = symbol or self.trading.symbol
        data_url = data_base_url or get_env("DELTA_DATA_BASE_URL", INDIA_LIVE_DATA_URL) or INDIA_LIVE_DATA_URL
        self.data_base_url = data_url.rstrip("/")
        self.data = data_client or DeltaExchangeClient(base_url=self.data_base_url)
        self.entry_hour_ist = env_int("ETH_ENTRY_HOUR_IST", DEFAULT_ENTRY_HOUR_IST)
        self.target_pct = env_float("ETH_TARGET_PCT", CLOSE_TARGET_PCT)
        self.position_lots = env_int("ETH_POSITION_LOTS", DEFAULT_POSITION_LOTS)
        self.pullback_resolution = get_env("ETH_PULLBACK_RESOLUTION", DEFAULT_PULLBACK_RESOLUTION) or DEFAULT_PULLBACK_RESOLUTION
        self.entry_resolution = get_env("ETH_ENTRY_RESOLUTION", DEFAULT_ENTRY_RESOLUTION) or DEFAULT_ENTRY_RESOLUTION
        self.state_path = state_path or LIVE_STATE_DIR / f"{self.symbol}_volume_bias_state.json"
        self.state = load_strategy_state(self.state_path, self.symbol)

    def _save_state(self) -> None:
        save_strategy_state(self.state_path, self.state)

    def _log(self, message: str) -> None:
        append_log(self.state, message)

    def _send_email(self, result) -> None:
        if result.success:
            self._log(f"Email sent: {result.message}")
        elif result.message and "disabled" not in result.message.lower():
            self._log(f"Email failed: {result.message}")

    def set_enabled(self, enabled: bool) -> None:
        self.state.enabled = enabled
        self._log("Strategy ENABLED" if enabled else "Strategy DISABLED")
        self._save_state()

    def _reset_session_if_new_day(self, day: str) -> None:
        if self.state.session.day == day:
            return
        self.state.session = LiveSessionState(day=day)

    def _round_price(self, price: float) -> float:
        tick = self.trading.get_product_tick_size(self.symbol)
        if tick <= 0:
            return price
        return round(round(price / tick) * tick, 8)

    def _place_protective_orders(self, side: str, stop_loss: float, target: float, lots: int) -> None:
        exit_side_name = exit_side(side)
        mark = self.trading.get_mark_price(self.symbol)
        self.trading.place_stop_order(
            size=lots, side=exit_side_name, stop_price=stop_loss, symbol=self.symbol, reduce_only=True, mark_price=mark
        )
        self.trading.place_limit_order(
            size=lots, side=exit_side_name, limit_price=target, symbol=self.symbol, reduce_only=True
        )

    def _rollback_entry(self, lots: int, close_side: str, reason: str) -> list[str]:
        self._log(reason)
        try:
            self.trading.place_market_order(size=lots, side=close_side, symbol=self.symbol, reduce_only=True)
            return [reason]
        except Exception as rollback_exc:  # noqa: BLE001
            detail = f"CRITICAL: {lots} lots open; rollback failed: {rollback_exc}"
            self._log(detail)
            return [reason, detail]

    def _execute_entry(self, side: str, mark_price: float, pullback) -> list[str]:
        lots = self.position_lots
        stop_loss = self._round_price(pullback_stop_loss(pullback, side))
        target = self._round_price(target_price(side, mark_price, self.target_pct))
        if not stop_is_valid(side, mark_price, stop_loss):
            self.state.session.after_pullback_ts = pullback.timestamp
            msg = (
                f"Skip {side}: pullback wick SL {stop_loss:.2f} is not valid vs mark {mark_price:.2f} "
                "— waiting for next 15m pullback"
            )
            self._log(msg)
            return [msg]
        if self.trading.get_open_position_size(self.symbol) != 0:
            msg = "Entry blocked: exchange already has a position"
            self._log(msg)
            return [msg]

        self.trading.place_market_order(size=lots, side=order_side(side), symbol=self.symbol)
        try:
            self._place_protective_orders(side, stop_loss, target, lots)
        except Exception as exc:  # noqa: BLE001
            return self._rollback_entry(lots, exit_side(side), f"Protective orders failed — rolling back: {exc}")

        session = self.state.session
        session.pullback = {"timestamp": pullback.timestamp, "high": pullback.high, "low": pullback.low}
        self.state.position = LivePositionState(
            side=side,
            entry_price=mark_price,
            stop_loss=stop_loss,
            target=target,
            entry_ts=pullback.timestamp,
            entry_lots=lots,
            pullback_high=pullback.high,
            pullback_low=pullback.low,
            initial_stop_loss=stop_loss,
        )
        action = (
            f"ENTER {side.upper()} {lots} lots @ ~{mark_price:.2f}, "
            f"SL {stop_loss:.2f} (wick), TP {target:.2f} (+{self.target_pct:.0f}%)"
        )
        self._log(action)
        self._send_email(
            send_entry_signal_email(
                symbol=self.symbol,
                side=side,
                entry_price=mark_price,
                stop_loss=stop_loss,
                target=target,
                entry_lots=lots,
                entry_ts=pullback.timestamp,
                buy_volume=session.buy_volume,
                sell_volume=session.sell_volume,
                pullback_high=pullback.high,
                pullback_low=pullback.low,
            )
        )
        return [action]

    def _notify_exit(self, position: LivePositionState, mark_price: float, *, take_profit: bool, exchange: bool) -> None:
        if take_profit:
            self._send_email(
                send_take_profit_email(
                    symbol=self.symbol,
                    side=position.side,
                    entry_price=position.entry_price,
                    exit_price=mark_price,
                    lots=position.entry_lots,
                    target=position.target,
                )
            )
            return
        self._send_email(
            send_stop_loss_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=mark_price,
                lots=position.entry_lots,
                stop_loss=position.stop_loss,
                exit_type="exchange_stop" if exchange else "stop_loss",
            )
        )

    def _finish_exit(self, position: LivePositionState, mark_price: float) -> None:
        session = self.state.session
        points = round(signed_points(position.side, position.entry_price, mark_price), 2)
        if points > 0:
            session.wins_today += 1
        elif points < 0:
            session.losses_today += 1
        session.after_pullback_ts = position.entry_ts
        session.traded_today = day_limit_reached(session.wins_today, session.losses_today)
        if session.traded_today:
            reason = "2 wins" if session.wins_today >= 2 else "2 losses"
            self._log(f"{reason} today — no more entries today")
            return
        initial = position.initial_stop_loss or position.stop_loss
        if abs(position.stop_loss - initial) < 1e-8:
            self._log("Stop hit pullback wick — waiting for next 15m pullback + 1m confirmation")
            return
        self._log("Trade closed — waiting for next 15m pullback + 1m confirmation")

    def _close_at_market(self, position: LivePositionState, mark_price: float, reason: str) -> list[str]:
        take_profit = reason.startswith("TAKE PROFIT")
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.close_position_at_market(symbol=self.symbol)
        self.state.position = None
        self._finish_exit(position, mark_price)
        action = f"{reason} {position.entry_lots} lots @ ~{mark_price:.2f}"
        self._log(action)
        self._notify_exit(position, mark_price, take_profit=take_profit, exchange=False)
        return [action]

    def _sync_exchange_flat(self, position: LivePositionState, mark_price: float) -> list[str]:
        take_profit = abs(mark_price - position.target) <= abs(mark_price - position.stop_loss)
        reason = "TAKE PROFIT" if take_profit else "STOP LOSS"
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.state.position = None
        self._finish_exit(position, mark_price)
        action = f"{reason} (exchange flat) {position.entry_lots} lots @ ~{mark_price:.2f}"
        self._log(action)
        self._notify_exit(position, mark_price, take_profit=take_profit, exchange=True)
        return [action]

    def _apply_trail_stop(self, position: LivePositionState, new_stop: float, mark_price: float) -> list[str]:
        new_stop = self._round_price(new_stop)
        self.trading.cancel_open_orders(symbol=self.symbol)
        try:
            self._place_protective_orders(position.side, new_stop, position.target, position.entry_lots)
        except Exception as exc:  # noqa: BLE001
            try:
                self._place_protective_orders(
                    position.side, position.stop_loss, position.target, position.entry_lots
                )
            except Exception as restore_exc:  # noqa: BLE001
                return self._close_at_market(
                    position,
                    mark_price,
                    f"STOP LOSS (trail replace failed: {exc}; restore failed: {restore_exc})",
                )
            msg = f"Trail SL failed, restored prior SL {position.stop_loss:.2f}: {exc}"
            self._log(msg)
            return [msg]
        locked = favorable_move_pct(position.side, position.entry_price, mark_price)
        position.stop_loss = new_stop
        action = f"TRAIL SL to {new_stop:.2f} (move {locked:.2f}%)"
        self._log(action)
        return [action]

    def _manage_open_position(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []
        exchange_size = self.trading.get_open_position_size(self.symbol)
        if exchange_size == 0:
            return self._sync_exchange_flat(position, mark_price)
        expected = position.entry_lots if position.side == "long" else -position.entry_lots
        if exchange_size != expected:
            msg = f"Position mismatch: exchange {exchange_size} vs tracked {expected}"
            self._log(msg)
            return [msg]
        initial_stop = position.initial_stop_loss or position.stop_loss
        action, new_stop = decide_open_trade(
            position.side,
            position.entry_price,
            initial_stop,
            position.stop_loss,
            position.target,
            mark_price,
        )
        if action == "take_profit":
            return self._close_at_market(position, mark_price, "TAKE PROFIT")
        if action == "stop_loss":
            return self._close_at_market(position, mark_price, "STOP LOSS")
        if action == "trail":
            return self._apply_trail_stop(position, new_stop, mark_price)
        return []

    def _maybe_enter(
        self,
        pullback_bars: list[dict],
        entry_bars_1m: list[dict],
        mark_price: float,
    ) -> list[str]:
        session = self.state.session
        if self.state.position is not None or session.traded_today or not session.bias:
            if session.traded_today and self.state.position is None:
                return [
                    f"Day closed ({session.wins_today} wins / {session.losses_today} losses) "
                    "— no more entries today"
                ]
            return []
        if not now_in_entry_window(self.entry_hour_ist):
            return [f"Observing India session volume — entries start at {self.entry_hour_ist:02d}:00 IST"]
        pullback, confirm = pullback_and_confirmation(
            pullback_bars,
            entry_bars_1m,
            session.day,
            session.bias,
            self.entry_hour_ist,
            self.pullback_resolution,
            session.after_pullback_ts,
        )
        if pullback is None:
            waiting = "next 15m pullback" if session.after_pullback_ts else "one 15m pullback"
            return [f"Bias {session.bias.upper()} locked — waiting for {waiting}"]
        session.pullback = {"timestamp": pullback.timestamp, "high": pullback.high, "low": pullback.low}
        if confirm is None:
            return ["15m pullback seen — waiting for 1m confirmation"]
        return self._execute_entry(session.bias, mark_price, pullback)

    def _update_volume_bias(self, closed_bars: list[dict]) -> None:
        session = self.state.session
        bias_bars, _entry_bars = split_session_bars(closed_bars, session.day, self.entry_hour_ist)
        measured = measure_volume_bias(bias_bars)
        session.buy_volume = measured.buy_volume
        session.sell_volume = measured.sell_volume
        if not now_in_entry_window(self.entry_hour_ist):
            session.bias = measured.side
            session.bias_locked = False
            return
        if session.bias_locked:
            return
        session.bias = measured.side
        session.bias_locked = True
        self._log(
            f"Bias locked {measured.label} (buy vol {measured.buy_volume:.4f} / sell vol {measured.sell_volume:.4f})"
        )

    def tick(self, *, dry_run: bool = False) -> LiveTickResult:
        if not self.trading.is_configured:
            return LiveTickResult(success=False, error="Delta API credentials not configured")
        if not self.state.enabled and not dry_run:
            return LiveTickResult(success=True, actions=["Strategy disabled"], in_position=self.state.position is not None)
        try:
            pullback_rows = self.data.fetch_historical_ohlcv(
                symbol=self.symbol, resolution=self.pullback_resolution, days=2
            )
            entry_rows = self.data.fetch_historical_ohlcv(
                symbol=self.symbol, resolution=self.entry_resolution, days=2
            )
            mark_price = self.data.fetch_mark_price(self.symbol)
            day = india_today()
            self._reset_session_if_new_day(day)
            now_ts = datetime.now(timezone.utc).timestamp()
            closed_15m = closed_bars_on_day(
                pullback_rows, day, now_ts, RESOLUTION_SECONDS.get(self.pullback_resolution, 900)
            )
            closed_1m = closed_bars_on_day(
                entry_rows, day, now_ts, RESOLUTION_SECONDS.get(self.entry_resolution, 60)
            )
            self._update_volume_bias(closed_15m)
            actions: list[str] = []
            if self.state.position is not None:
                actions.extend(["[DRY RUN] Manage position"] if dry_run else self._manage_open_position(mark_price))
            if self.state.position is None:
                if self.trading.get_open_position_size(self.symbol) != 0:
                    actions.append("Orphan position on exchange — close on Delta before new entries")
                elif dry_run:
                    actions.append("[DRY RUN] Scan complete — no orders placed")
                else:
                    actions.extend(self._maybe_enter(closed_15m, closed_1m, mark_price))
            if closed_1m:
                self.state.session.last_processed_ts = closed_1m[-1]["timestamp"]
            self._save_state()
            session = self.state.session
            return LiveTickResult(
                success=True,
                actions=actions or ["No action this tick"],
                mark_price=mark_price,
                buy_volume=session.buy_volume,
                sell_volume=session.sell_volume,
                bias=session.bias,
                exchange_position=self.trading.get_open_position_size(self.symbol),
                in_position=self.state.position is not None,
            )
        except Exception as exc:  # noqa: BLE001
            return LiveTickResult(success=False, error=str(exc))
