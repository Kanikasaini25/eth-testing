from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import LIVE_STATE_DIR, STRATEGIES_DIR, ensure_data_dirs
from src.delta_data import DeltaExchangeClient
from src.delta_trading import DeltaTradingClient
from src.email_notify import (
    send_entry_signal_email,
    send_stop_loss_email,
    send_take_profit_email,
)
from src.poc_strategy import (
    M15_SECONDS,
    PocState,
    SessionLevels,
    closed_bars,
    group_bars_by_day,
    hydrate_away_side,
    process_m15_bar,
    sync_session_state,
)
from src.risk import fill_risk_allowed, lots_for_risk, reached_r
from src.rule_extractor import TradingRule, rules_from_json

STOP_TICK_SIZE = 0.05
DEFAULT_ENTRY_LOTS = 100
ETHUSD_USD_PER_POINT = 0.01


def _from_dict(cls, data: dict):
    allowed = {item.name for item in fields(cls)}
    return cls(**{key: value for key, value in data.items() if key in allowed})


@dataclass
class LivePositionState:
    side: str
    entry_price: float
    stop_loss: float
    target_1: float
    target_2: float
    entry_line: str
    entry_ts: str
    entry_lots: int = DEFAULT_ENTRY_LOTS
    original_stop: float = 0.0


@dataclass
class LiveSessionState:
    day: str = ""
    trades_in_sequence: int = 0
    full_sl_count: int = 0
    last_processed_ts: str = ""
    used_levels: list[str] = field(default_factory=list)
    poc: float | None = None
    val: float | None = None
    vah: float | None = None
    bias: str = ""


@dataclass
class LiveStrategyState:
    enabled: bool = False
    symbol: str = "ETHUSD"
    session: LiveSessionState = field(default_factory=LiveSessionState)
    position: LivePositionState | None = None
    logs: list[str] = field(default_factory=list)


@dataclass
class LiveTickResult:
    success: bool
    actions: list[str] = field(default_factory=list)
    mark_price: float | None = None
    poc: float | None = None
    val: float | None = None
    vah: float | None = None
    bias: str = ""
    exchange_position: int = 0
    in_position: bool = False
    error: str = ""


def default_rules_path() -> Path:
    return STRATEGIES_DIR / "wI9b968AvW8_rules.json"


def load_poc_rule(path: Path | None = None) -> TradingRule:
    rules_path = path or default_rules_path()
    if not rules_path.exists():
        raise FileNotFoundError(f"Strategy rules not found: {rules_path}")
    rules = rules_from_json(rules_path.read_text(encoding="utf-8"))
    for rule in rules:
        if rule.strategy_type in {"poc_value_area", "m15_poc"}:
            return rule
    raise ValueError(f"No 15m POC strategy in {rules_path}")


class LivePocRunner:
    """Run 15-minute previous-day POC / value-area reaction on Delta."""

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
        self.rule = rule or load_poc_rule(rules_path)
        self.state_path = state_path or LIVE_STATE_DIR / f"{self.symbol}_live_state.json"
        self.state = self._load_state()

    def _load_state(self) -> LiveStrategyState:
        if not self.state_path.exists():
            return LiveStrategyState(symbol=self.symbol)
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        session = _from_dict(LiveSessionState, raw.pop("session", {}))
        position_raw = raw.pop("position", None)
        position = _from_dict(LivePositionState, position_raw) if position_raw else None
        return _from_dict(LiveStrategyState, {**raw, "session": session, "position": position})

    def _save_state(self) -> None:
        self.state_path.write_text(json.dumps(asdict(self.state), indent=2), encoding="utf-8")

    def _log(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        self.state.logs.append(f"[{stamp}] {message}")
        self.state.logs = self.state.logs[-100:]

    def _send_email(self, result) -> None:
        if result.success:
            self._log(f"Email sent: {result.message}")
        elif result.message and "disabled" not in result.message.lower():
            self._log(f"Email failed: {result.message}")

    def _params(self) -> dict[str, Any]:
        return self.rule.parameters

    def _poc_state(self) -> PocState:
        session = self.state.session
        levels = None
        if session.poc is not None and session.val is not None and session.vah is not None:
            levels = SessionLevels(
                day=session.day,
                poc=session.poc,
                val=session.val,
                vah=session.vah,
                bias=session.bias or "flat",
                session_open=0.0,
                session_close=0.0,
            )
        return PocState(
            current_day=session.day,
            levels=levels,
            used_levels=set(session.used_levels),
        )

    def _apply_poc_state(self, poc_state: PocState) -> None:
        session = self.state.session
        session.used_levels = sorted(poc_state.used_levels)
        if poc_state.levels is None:
            session.poc = None
            session.val = None
            session.vah = None
            session.bias = ""
            return
        session.poc = poc_state.levels.poc
        session.val = poc_state.levels.val
        session.vah = poc_state.levels.vah
        session.bias = poc_state.levels.bias

    def _order_side(self, side: str) -> str:
        return "buy" if side == "long" else "sell"

    def _exit_side(self, side: str) -> str:
        return "sell" if side == "long" else "buy"

    def _adjust_entry_stop_price(self, side: str, stop_loss: float, mark: float) -> float:
        tick = self.trading.get_product_tick_size(self.symbol)
        if side == "short" and stop_loss <= mark + tick:
            return mark + max(tick, 3.0)
        if side == "long" and stop_loss >= mark - tick:
            return mark - max(tick, 3.0)
        return stop_loss

    def _place_entry_stop(self, side: str, stop_side: str, stop_loss: float, lots: int) -> float:
        mark = self.trading.get_mark_price(self.symbol)
        adjusted = self._adjust_entry_stop_price(side, stop_loss, mark)
        self.trading.place_stop_order(
            size=lots,
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

    def _execute_entry(
        self,
        side: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        entry_line: str,
        entry_ts: str,
    ) -> list[str]:
        params = self._params()
        wallet = float(params.get("starting_wallet_usd", 10000))
        entry_lots = lots_for_risk(
            wallet,
            abs(entry_price - stop_loss),
            risk_pct=float(params.get("risk_pct_per_trade", 1.0)),
            usd_per_point=float(params.get("usd_per_point_per_lot", ETHUSD_USD_PER_POINT)),
            min_lots=int(params.get("min_lots", 1)),
            max_lots=int(params.get("position_lots", DEFAULT_ENTRY_LOTS)),
            use_risk_sizing=bool(params.get("use_risk_sizing", True)),
            fallback_lots=int(params.get("position_lots", DEFAULT_ENTRY_LOTS)),
            entry_price=entry_price,
            max_leverage=float(params.get("max_leverage", 1.0)),
        )
        if entry_lots < 1:
            return [f"Entry skipped: ${wallet:,.0f} wallet cannot fit 1 lot at this price"]
        order_side = self._order_side(side)
        stop_side = self._exit_side(side)
        if self.trading.get_open_position_size(self.symbol) != 0:
            msg = "Entry blocked: exchange already has a position — flatten on Delta first"
            self._log(msg)
            return [msg]

        self.trading.place_market_order(size=entry_lots, side=order_side, symbol=self.symbol)
        fill_price = self.trading.get_mark_price(self.symbol) or entry_price
        try:
            placed_sl = self._place_entry_stop(side, stop_side, stop_loss, entry_lots)
        except Exception as exc:
            self._log(f"Stop order failed — rolling back {entry_lots} lots")
            try:
                self.trading.place_market_order(
                    size=entry_lots, side=stop_side, symbol=self.symbol, reduce_only=True
                )
                return [f"Entry aborted: {exc}"]
            except Exception as rollback_exc:
                return [f"CRITICAL: {entry_lots} lots open, stop and rollback failed: {rollback_exc}"]
        try:
            self._place_take_profit_limit(side, target, entry_lots)
        except Exception as exc:
            self._log(f"Take-profit limit failed, managing in software: {exc}")

        self.state.position = LivePositionState(
            side=side,
            entry_price=fill_price,
            stop_loss=placed_sl,
            target_1=target,
            target_2=target,
            entry_line=entry_line,
            entry_ts=entry_ts,
            entry_lots=entry_lots,
            original_stop=placed_sl,
        )
        action = (
            f"ENTER {side.upper()} {entry_lots} lots @ ~{fill_price:.2f}, "
            f"SL {placed_sl:.2f}, TP {target:.2f} ({entry_line})"
        )
        self._log(action)
        self._send_email(
            send_entry_signal_email(
                symbol=self.symbol,
                side=side,
                entry_price=fill_price,
                stop_loss=placed_sl,
                target_1=target,
                target_2=target,
                entry_lots=entry_lots,
                partial_lots=entry_lots,
                runner_lots=0,
                entry_line=entry_line,
                entry_ts=entry_ts,
                upper_level=self.state.session.vah,
                lower_level=self.state.session.val,
            )
        )
        return [action]

    def _execute_take_profit(self, position: LivePositionState, exit_price: float) -> list[str]:
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.close_position_at_market(symbol=self.symbol)
        self.state.position = None
        action = f"TAKE PROFIT {position.entry_lots} lots @ ~{exit_price:.2f}"
        self._log(action)
        self._send_email(
            send_take_profit_email(
                symbol=self.symbol,
                side=position.side,
                entry_price=position.entry_price,
                exit_price=exit_price,
                lots=position.entry_lots,
                target=position.target_1,
            )
        )
        return [action]

    def _execute_full_stop(self, position: LivePositionState, exit_price: float) -> list[str]:
        self.trading.cancel_open_orders(symbol=self.symbol)
        self.trading.close_position_at_market(symbol=self.symbol)
        self.state.session.full_sl_count += 1
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
                partial_was_taken=False,
            )
        )
        return [action]

    def _maybe_move_full_stop_to_breakeven(
        self, position: LivePositionState, mark_price: float
    ) -> str | None:
        original = position.original_stop if position.original_stop > 0 else position.stop_loss
        if abs(position.stop_loss - position.entry_price) <= STOP_TICK_SIZE:
            return None
        r_multiple = float(self._params().get("breakeven_r_multiple", 1.5))
        if not reached_r(
            position.side,
            position.entry_price,
            original,
            mark_price,
            mark_price,
            r_multiple=r_multiple,
        ):
            return None
        self.trading.cancel_open_orders(symbol=self.symbol)
        placed = self._place_entry_stop(
            position.side, self._exit_side(position.side), position.entry_price, position.entry_lots
        )
        try:
            self._place_take_profit_limit(position.side, position.target_1, position.entry_lots)
        except Exception as exc:
            self._log(f"Take-profit limit failed after breakeven: {exc}")
        position.stop_loss = placed
        return f"Moved stop to breakeven @ {placed:.2f}"

    def _manage_open_position(self, mark_price: float) -> list[str]:
        position = self.state.position
        if position is None:
            return []
        if self.trading.get_open_position_size(self.symbol) == 0:
            self.trading.cancel_open_orders(symbol=self.symbol)
            near_tp = (
                mark_price >= position.target_1 - 1.0
                if position.side == "long"
                else mark_price <= position.target_1 + 1.0
            )
            if near_tp:
                return self._execute_take_profit(position, mark_price)
            self.state.session.full_sl_count += 1
            self.state.position = None
            action = f"Position closed on exchange @ ~{mark_price:.2f}"
            self._log(action)
            return [action]
        hit_tp = (
            mark_price >= position.target_1 if position.side == "long" else mark_price <= position.target_1
        )
        hit_sl = (
            mark_price <= position.stop_loss if position.side == "long" else mark_price >= position.stop_loss
        )
        if hit_tp:
            return self._execute_take_profit(position, mark_price)
        if hit_sl:
            return self._execute_full_stop(position, mark_price)
        if bool(self._params().get("move_stop_to_breakeven", True)):
            moved = self._maybe_move_full_stop_to_breakeven(position, mark_price)
            return [moved] if moved else []
        return []

    def _session_limits_reached(self) -> bool:
        params = self._params()
        session = self.state.session
        max_trades = int(params.get("max_trades_per_sequence", 0))
        max_full_sl = int(params.get("max_full_stop_losses_per_session", 0))
        if max_full_sl > 0 and session.full_sl_count >= max_full_sl:
            return True
        return max_trades > 0 and session.trades_in_sequence >= max_trades

    def _process_entry_bar(self, row: dict, poc_state: PocState) -> list[str]:
        if self.state.position is not None or self._session_limits_reached():
            return []
        params = self._params()
        max_sl = float(params.get("max_stop_loss_points", 10.0))
        signal = process_m15_bar(
            row,
            poc_state,
            touch_points=float(params.get("touch_points", 2.0)),
            min_target=float(params.get("partial_target_points", 15)),
            reward_r=float(params.get("reward_r_multiple", 2.0)),
            min_sl_points=float(params.get("min_stop_loss_points", 5.0)),
            max_sl_points=max_sl,
            min_reward_to_risk=float(params.get("min_reward_to_risk", 1.5)),
            use_session_filter=bool(params.get("use_session_filter", True)),
            session_start_hour_utc=int(params.get("session_start_hour_utc", 8)),
            session_end_hour_utc=int(params.get("session_end_hour_utc", 20)),
            use_htf_bias=bool(params.get("use_htf_bias", True)),
            trade_poc=bool(params.get("trade_poc", True)),
            trade_val=bool(params.get("trade_val", False)),
            trade_vah=bool(params.get("trade_vah", False)),
            require_return=bool(params.get("require_return", True)),
            min_away_points=float(params.get("min_away_points", 12.0)),
            min_sweep_points=float(params.get("min_sweep_points", 2.0)),
            min_close_beyond=float(params.get("min_close_beyond", 2.0)),
            min_body_points=float(params.get("min_body_points", 0.0)),
            require_open_pullback=bool(params.get("require_open_pullback", True)),
            max_intraday_range=float(params.get("max_intraday_range", 100.0)),
            skip_monday=bool(params.get("skip_monday", True)),
        )
        self._apply_poc_state(poc_state)
        if signal is None:
            return []
        fill = float(row["close"])
        if not fill_risk_allowed(
            fill,
            signal.stop_loss,
            max_sl_points=max_sl,
            min_reward_to_risk=float(params.get("min_reward_to_risk", 2.0)),
            min_target=float(params.get("partial_target_points", 15)),
            reward_r=float(params.get("reward_r_multiple", 2.0)),
        ):
            return [f"Skipped {signal.side}: fill stop fails quality check"]
        self.state.session.trades_in_sequence += 1
        return self._execute_entry(
            signal.side, fill, signal.stop_loss, signal.target, signal.entry_line, row["timestamp"]
        )

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
            lookback = int(self._params().get("swing_lookback_days", 5))
            m15_rows = self.data.fetch_historical_ohlcv(
                symbol=self.symbol, resolution="15m", days=lookback
            )
            mark_price = self.trading.get_mark_price(self.symbol)
            now_epoch = datetime.now(timezone.utc).timestamp()
            m15_closed = closed_bars(m15_rows, M15_SECONDS, now_epoch)
            by_day = group_bars_by_day(m15_closed)
            days = sorted(by_day)
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            poc_state = self._poc_state()
            if self.state.session.day != day:
                self.state.session.day = day
                self.state.session.trades_in_sequence = 0
                self.state.session.full_sl_count = 0
            bin_size = float(self._params().get("bin_size", 1.0))
            value_area_pct = float(self._params().get("value_area_pct", 0.70))

            def _sync_for(row_day: str) -> None:
                prior = [item for item in days if item < row_day]
                previous_day = prior[-1] if prior else None
                sync_session_state(
                    poc_state,
                    row_day,
                    previous_day,
                    by_day.get(previous_day) if previous_day else None,
                    bin_size=bin_size,
                    value_area_pct=value_area_pct,
                )

            _sync_for(day)
            self._apply_poc_state(poc_state)
            actions: list[str] = []
            if self.state.position is not None:
                actions.extend(
                    [f"[DRY RUN] Manage position @ {mark_price:.2f}"]
                    if dry_run
                    else self._manage_open_position(mark_price)
                )
            elif self.trading.get_open_position_size(self.symbol) != 0:
                actions.append("Orphan position on exchange — close on Delta before new entries")
            else:
                last_ts = self.state.session.last_processed_ts
                min_away = float(self._params().get("min_away_points", 12.0))
                prior_today = [
                    row
                    for row in m15_closed
                    if row["timestamp"][:10] == day
                    and (not last_ts or row["timestamp"] <= last_ts)
                ]
                hydrate_away_side(poc_state, prior_today, min_away)
                new_bars = [row for row in m15_closed if row["timestamp"] > last_ts] if last_ts else []
                if not last_ts and m15_closed:
                    self.state.session.last_processed_ts = m15_closed[-1]["timestamp"]
                    actions.append("Warmed up — waiting for next 15m bar")
                else:
                    processed = 0
                    for row in new_bars:
                        _sync_for(row["timestamp"][:10])
                        if not dry_run:
                            actions.extend(self._process_entry_bar(row, poc_state))
                        processed += 1
                        self.state.session.last_processed_ts = row["timestamp"]
                        if self.state.position is not None:
                            break
                    if dry_run and processed:
                        actions.append(f"[DRY RUN] Scanned {processed} closed 15m bars")
                    elif processed and not actions:
                        actions.append(f"Scanned {processed} new 15m bars — no POC reaction")
            self._save_state()
            return LiveTickResult(
                success=True,
                actions=actions or ["No action this tick"],
                mark_price=mark_price,
                poc=self.state.session.poc,
                val=self.state.session.val,
                vah=self.state.session.vah,
                bias=self.state.session.bias,
                exchange_position=self.trading.get_open_position_size(self.symbol),
                in_position=self.state.position is not None,
            )
        except Exception as exc:
            return LiveTickResult(success=False, error=str(exc))

    def set_enabled(self, enabled: bool) -> None:
        self.state.enabled = enabled
        self._log("Strategy ENABLED" if enabled else "Strategy DISABLED")
        self._save_state()


LiveLiquidityRunner = LivePocRunner
load_liquidity_rule = load_poc_rule
