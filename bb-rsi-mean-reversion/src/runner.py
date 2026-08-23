"""Live loop: 1m signals, Asian filter, $14 kill-switch, isolated from other strategies."""

from __future__ import annotations

import time
from dataclasses import dataclass

from src.config import Settings
from src.delta_client import DeltaClient
from src.errors import DeltaAPIError, OrderError, StrategyError
from src.logger import scan_line, setup_logger, trade_line
from src.orders import OrderExecutor
from src.risk import build_trade_plan, price_pnl_usd, stop_hit, take_profit_hit, trading_fee_usd, trail_lock_price
from src.session import can_open_new_trade, session_label, utc_now
from src.state import DailyTracker, OpenPosition
from src.strategy import Signal, evaluate_closed_candle
from src.websocket_client import TickerFeed

logger = setup_logger()


@dataclass
class TickResult:
    success: bool
    action: str
    mark_price: float | None = None
    error: str = ""


class BBRSIRunner:
    def __init__(self, settings: Settings, dry_run: bool = False) -> None:
        self.settings = settings
        self.dry_run = dry_run or settings.dry_run
        self.client = DeltaClient(settings)
        self.tracker = DailyTracker(settings)
        self.orders = OrderExecutor(self.client, dry_run=self.dry_run)
        self.feed = TickerFeed(settings)

    def start_ws(self) -> None:
        self.feed.start()

    def stop_ws(self) -> None:
        self.feed.stop()

    def mark_price(self) -> float:
        if self.feed.mark_price is not None:
            return self.feed.mark_price
        return self.client.get_mark_price()

    def tick(self) -> TickResult:
        now = utc_now()
        if self.tracker.roll_trading_day(now):
            logger.info("IST day rolled — daily PnL and trade cap reset")

        try:
            mark = self.mark_price()
        except DeltaAPIError as exc:
            return TickResult(success=False, action="mark_failed", error=str(exc))

        if self.tracker.halted(now):
            until = self.tracker.halt_until_label(now)
            msg = f"Kill-switch active — sleeping until {until}"
            logger.info(msg)
            return TickResult(success=True, action=msg, mark_price=mark)

        unrealized = self._unrealized(mark)
        if self.tracker.should_kill(unrealized):
            return self._fire_kill_switch(mark)

        if self.tracker.state.position is not None:
            return self._manage_position(mark)

        return self._scan_for_entry(mark)

    def run_forever(self) -> None:
        self.start_ws()
        logger.info(
            "BB/RSI bot started symbol=%s dry_run=%s rest=%s",
            self.settings.symbol,
            self.dry_run,
            self.settings.rest_url,
        )
        try:
            while True:
                result = self.tick()
                if not result.success:
                    logger.error("Tick failed: %s", result.error)
                time.sleep(self.settings.poll_seconds)
        except KeyboardInterrupt:
            logger.info("Stopped by user")
        finally:
            self.stop_ws()

    def _unrealized(self, mark: float) -> float:
        position = self.tracker.state.position
        if position is None:
            return 0.0
        return self._gross_pnl(position, mark) - self._round_trip_fees(
            position.entry_price, mark, position
        )

    def _gross_pnl(self, position: OpenPosition, mark: float) -> float:
        return price_pnl_usd(
            position.side,
            position.entry_price,
            mark,
            position.lots,
            position.contract_eth,
        )

    def _round_trip_fees(self, entry_price: float, exit_price: float, position) -> float:
        return trading_fee_usd(
            entry_price, position.lots, position.contract_eth, self.settings.fee_pct_per_side
        ) + trading_fee_usd(
            exit_price, position.lots, position.contract_eth, self.settings.fee_pct_per_side
        )

    def _fire_kill_switch(self, mark: float) -> TickResult:
        position = self.tracker.state.position
        logger.error(
            "KILL SWITCH daily_pnl=%+.2f <= -%.2f — flattening",
            self.tracker.daily_pnl(self._unrealized(mark)),
            self.settings.daily_max_loss_usd,
        )
        try:
            self.orders.flatten()
        except Exception as exc:  # noqa: BLE001
            logger.error("Flatten during kill-switch failed: %s", exc)
        if position is not None:
            pnl = self._unrealized(mark)
            self.tracker.record_exit(exit_price=mark, pnl_usd=pnl, reason="kill_switch")
        self.tracker.trip_kill_switch()
        action = f"Kill-switch tripped — halt until {self.tracker.halt_until_label(utc_now())}"
        return TickResult(success=True, action=action, mark_price=mark)

    def _scan_for_entry(self, mark: float) -> TickResult:
        now = utc_now()
        session = session_label(now)
        if not can_open_new_trade(now):
            action = f"No entries ({session})"
            logger.info(
                "skip_entry session=%s mark=%.2f daily_pnl=%+.2f trades=%s/%s",
                session,
                mark,
                self.tracker.state.realized_pnl,
                self.tracker.state.trades_taken,
                self.settings.daily_trade_cap,
            )
            return TickResult(success=True, action=action, mark_price=mark)

        if not self.tracker.can_take_trade(now):
            if self.tracker.in_loss_cooldown(now):
                action = f"Loss cooldown — wait {self.settings.loss_cooldown_minutes}m after last loss"
            elif self.tracker.state.session_profit_taken:
                action = "Session locked after profit — wait for next open"
            elif self.tracker.state.session_sl_count >= self.settings.max_session_stops:
                action = f"Session SL cap ({self.settings.max_session_stops}) reached"
            else:
                action = (
                    f"Daily cap reached ({self.tracker.state.trades_taken}/"
                    f"{self.settings.daily_trade_cap})"
                )
            logger.info(action)
            return TickResult(success=True, action=action, mark_price=mark)

        candles = self.client.fetch_closed_candles()
        if not candles:
            return TickResult(success=True, action="Waiting for 1m candles", mark_price=mark)

        last_ts = candles[-1]["timestamp"]
        if last_ts == self.tracker.state.last_candle_ts:
            return TickResult(success=True, action="No new closed 1m candle", mark_price=mark)

        self.tracker.state.last_candle_ts = last_ts
        self.tracker.save()
        signal = evaluate_closed_candle(
            candles, after_session_stop=self.tracker.state.session_sl_count > 0
        )
        indicators = signal.indicators if signal else None
        logger.info(
            scan_line(
                close=float(candles[-1]["close"]),
                mark=mark,
                rsi=f"{indicators.rsi:.1f}" if indicators else "n/a",
                lower=f"{indicators.lower_band:.2f}" if indicators else "n/a",
                upper=f"{indicators.upper_band:.2f}" if indicators else "n/a",
                session=session,
                signal=signal.side.upper() if signal else "NONE",
                daily_pnl=self.tracker.state.realized_pnl,
                trades_today=self.tracker.state.trades_taken,
                trade_cap=self.settings.daily_trade_cap,
            )
        )
        if signal is None:
            return TickResult(success=True, action="No BB/RSI signal", mark_price=mark)
        return self._enter(signal, mark)

    def _enter(self, signal: Signal, mark: float) -> TickResult:
        candle = signal.candle
        try:
            plan = build_trade_plan(
                side=signal.side,
                entry_price=float(candle["close"]),
                candle_low=float(candle["low"]),
                candle_high=float(candle["high"]),
                risk_usd=self.settings.per_trade_stop_usd,
                take_profit_usd=self.settings.take_profit_usd,
                profit_lock_usd=self.settings.profit_lock_usd,
                max_profit_usd=self.settings.max_profit_usd,
                contract_eth=self.client.contract_eth(),
                tick_size=self.client.tick_size(),
                lots=self.settings.lots,
                fee_pct_per_side=self.settings.fee_pct_per_side,
                net_of_fees=self.settings.net_of_fees,
            )
            position = self.orders.enter(plan)
        except (OrderError, StrategyError, DeltaAPIError) as exc:
            logger.error("Entry failed: %s", exc)
            return TickResult(success=False, action="entry_failed", mark_price=mark, error=str(exc))

        self.tracker.record_entry(position)
        line = trade_line(
            signal=signal.side.upper(),
            entry=position.entry_price,
            sl=position.stop_price,
            tp=position.take_profit_price,
            daily_pnl=self.tracker.state.realized_pnl,
            trades_today=self.tracker.state.trades_taken,
            trade_cap=self.settings.daily_trade_cap,
            extra=f"lots={position.lots} rsi={signal.indicators.rsi:.1f}",
        )
        logger.info("ENTER %s", line)
        return TickResult(success=True, action=f"ENTER {line}", mark_price=mark)

    def _manage_position(self, mark: float) -> TickResult:
        position = self.tracker.state.position
        if position is None:
            return TickResult(success=True, action="Flat", mark_price=mark)

        if not self.dry_run:
            exchange_size = self.client.get_position_size()
            if exchange_size == 0:
                pnl = self._unrealized(mark)
                self.tracker.record_exit(exit_price=mark, pnl_usd=pnl, reason="exchange_flat")
                logger.info(
                    "Position closed on exchange @ %.2f pnl=%+.2f daily_pnl=%+.2f trades=%s/%s",
                    mark,
                    pnl,
                    self.tracker.state.realized_pnl,
                    self.tracker.state.trades_taken,
                    self.settings.daily_trade_cap,
                )
                return TickResult(success=True, action="Synced flat from exchange", mark_price=mark)

        pnl = self._unrealized(mark)
        gross = self._gross_pnl(position, mark)
        if gross >= self.settings.max_profit_usd:
            return self._exit_now(position, mark, "max_profit")
        if stop_hit(position.side, mark, position.stop_price):
            return self._exit_now(position, mark, "stop_loss")
        if take_profit_hit(position.side, mark, position.take_profit_price) and not self.settings.trail_to_max_profit:
            return self._exit_now(position, mark, "take_profit")
        if self._maybe_lock_profit(position, gross, mark):
            return TickResult(success=True, action="Profit lock moved SL", mark_price=mark)

        logger.info(
            "MANAGE %s mark=%.2f pnl=%+.2f sl=%.2f tp=%.2f daily_pnl=%+.2f trades=%s/%s",
            position.side.upper(),
            mark,
            pnl,
            position.stop_price,
            position.take_profit_price,
            self.tracker.daily_pnl(pnl),
            self.tracker.state.trades_taken,
            self.settings.daily_trade_cap,
        )
        return TickResult(success=True, action="Managing open position", mark_price=mark)

    def _maybe_lock_profit(self, position: OpenPosition, pnl: float, mark: float) -> bool:
        if not self.settings.enable_trailing_lock:
            return False
        if pnl < self.settings.profit_lock_usd:
            return False

        new_stop = position.profit_lock_price
        if self.settings.trail_to_max_profit:
            new_stop = trail_lock_price(
                position.side, mark, position.profit_lock_price, position.entry_price
            )

        if position.side == "long" and new_stop <= position.stop_price:
            return False
        if position.side == "short" and new_stop >= position.stop_price:
            return False

        try:
            self.orders.update_stop(position, new_stop)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to move profit-lock stop: %s", exc)
            return False

        position.stop_price = new_stop
        position.profit_locked = True
        self.tracker.save()
        logger.info("Profit lock SL -> %.2f (pnl=%+.2f)", new_stop, pnl)
        return True

    def _exit_now(self, position: OpenPosition, mark: float, reason: str) -> TickResult:
        try:
            self.orders.flatten()
        except Exception as exc:  # noqa: BLE001
            logger.error("Exit flatten failed (%s): %s", reason, exc)
        pnl = self._unrealized(mark)
        self.tracker.record_exit(exit_price=mark, pnl_usd=pnl, reason=reason)
        logger.info(
            "EXIT %s @ %.2f pnl=%+.2f daily_pnl=%+.2f trades=%s/%s",
            reason,
            mark,
            pnl,
            self.tracker.state.realized_pnl,
            self.tracker.state.trades_taken,
            self.settings.daily_trade_cap,
        )
        if self.tracker.should_kill():
            self.tracker.trip_kill_switch()
        return TickResult(success=True, action=f"EXIT {reason} pnl={pnl:+.2f}", mark_price=mark)
