from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from src.backtest import (
    BacktestParams,
    BacktestResult,
    bar_seconds_for_resolution,
    run_pattern_backtest,
)
from src.config import LIVE_STATE_PATH, get_candle_base_url, get_env
from src.delta_data import DeltaExchangeClient, closed_ohlcv
from src.delta_trading import DeltaTradingClient
from src.email_notify import notify_event
from src.product_specs import backtest_params_from_env
from src.strategy import EntrySignal
from src.symbols import resolve_delta_symbol

CANDLE_API_URL = get_candle_base_url()
SIGNAL_DAYS = 5
M1_DAYS = 3


def live_params(lots: int = 100) -> BacktestParams:
    """Hammer / Shooting Star params (same as Streamlit)."""
    params = backtest_params_from_env(get_env("DELTA_SYMBOL", "PAXGUSD"))
    params.position_lots = max(int(lots), 1)
    return params


def signal_on_last_bar(
    signal_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams,
    *,
    bar_seconds: int = 900,
) -> EntrySignal | None:
    signal, _result, _ts = scan_closed_bars(signal_rows, m1_rows, params, bar_seconds=bar_seconds)
    return signal


def scan_closed_bars(
    signal_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams,
    *,
    bar_seconds: int = 900,
) -> tuple[EntrySignal | None, BacktestResult | None, str]:
    if not m1_rows:
        return None, None, "no closed 1m candles"
    entries: list[EntrySignal] = []
    result = run_pattern_backtest(
        signal_rows,
        m1_rows,
        params,
        bar_seconds=bar_seconds,
        entry_log=entries,
    )
    last_ts = m1_rows[-1]["timestamp"]
    signal = entries[-1] if entries and entries[-1].entry_ts == last_ts else None
    return signal, result, last_ts


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _status_log(last_ts: str, result: BacktestResult | None) -> str:
    if result is None:
        return f"{_utc_now()} | last 1m {last_ts} | no data"
    pending = "no pattern"
    if result.pending_side:
        kind = "HAMMER" if result.pending_side == "long" else "SHOOTING STAR"
        pending = (
            f"{kind} pending | level {result.pending_swing:.2f} | "
            f"SL {result.pending_sweep:.2f} @ {result.pending_grab_ts}"
        )
    return (
        f"{_utc_now()} | last 1m {last_ts} close {result.last_close:.2f} | {pending}"
    )


def _order_log_lines(
    signal: EntrySignal,
    *,
    mode: str,
    trade: str,
    lots: int,
    fill: float | None = None,
    tp_lots: int = 0,
    runner: int = 0,
    runner_tp: float = 0.0,
    stop: float | None = None,
    target: float | None = None,
) -> list[str]:
    stop = signal.stop_loss if stop is None else stop
    target = signal.target if target is None else target
    pattern = "Hammer high" if signal.side == "long" else "Shooting Star low"
    lines = [
        f"{_utc_now()} | {mode} ORDER {trade} {lots} lots",
        f"  Order time:         {signal.entry_ts}",
        f"  Pattern time:       {signal.grab_ts}",
        f"  {pattern}:          {signal.swing_price:.2f}",
        f"  Stop:               {stop:.2f}",
        f"  Signal entry:       {signal.entry_price:.2f}",
    ]
    if fill is not None:
        lines.append(f"  Fill price:         {fill:.2f}")
    lines.extend(
        [
            f"  TP 80% ({tp_lots or lots} lots): {target:.2f}",
            f"  Runner {runner} lots:    {runner_tp:.2f}",
        ]
    )
    return lines


def _scale_out_lots(total: int, pct: float) -> int:
    if pct <= 0 or pct >= 100 or total < 2:
        return 0
    closed = int(total * pct / 100.0)
    return min(max(closed, 1), total - 1)


def round_to_tick(price: float, tick: float) -> float:
    if tick <= 0:
        return round(price, 2)
    return round(round(price / tick) * tick, 8)


@dataclass
class LiveState:
    last_entry_ts: str = ""
    stage: str = "flat"
    side: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target: float = 0.0
    runner_target: float = 0.0
    lots: int = 0
    runner_lots: int = 0


def load_state() -> LiveState:
    if not LIVE_STATE_PATH.exists():
        return LiveState()
    payload = json.loads(LIVE_STATE_PATH.read_text())
    allowed = set(LiveState.__dataclass_fields__)
    return LiveState(**{key: value for key, value in payload.items() if key in allowed})


def save_state(state: LiveState) -> None:
    LIVE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LIVE_STATE_PATH.write_text(json.dumps(asdict(state), indent=2))


def _exit_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def _notify(subject: str, lines: list[str]) -> str:
    result = notify_event(subject, lines)
    if result.success:
        return result.message
    return f"Email not sent: {result.message}"


def _can_enter(exchange_size: int, side: str, full_lots: int) -> bool:
    if abs(exchange_size) >= full_lots:
        return False
    if exchange_size > 0 and side == "short":
        return False
    if exchange_size < 0 and side == "long":
        return False
    return True


class LiveGrabRunner:
    """Live Hammer / Shooting Star runner on Delta India."""

    def __init__(self, params: BacktestParams | None = None, symbol: str = "ETHUSD") -> None:
        self.params = params or live_params()
        resolved, _notice = resolve_delta_symbol(symbol)
        self.symbol = resolved
        self.candle_resolution = (get_env("DELTA_RESOLUTION", "15m") or "15m").strip()
        if self.candle_resolution in {"1d", "1w"}:
            self.candle_resolution = "15m"
        self.bar_seconds = bar_seconds_for_resolution(self.candle_resolution)
        self.candles = DeltaExchangeClient(base_url=CANDLE_API_URL)
        self.broker = DeltaTradingClient(symbol=resolved)
        self.state = load_state()

    def latest_signal(self) -> tuple[EntrySignal | None, str, BacktestResult | None]:
        signal_rows = closed_ohlcv(
            self.candles.fetch_historical_ohlcv(
                self.symbol, self.candle_resolution, days=SIGNAL_DAYS
            ),
            self.candle_resolution,
        )
        m1 = closed_ohlcv(
            self.candles.fetch_historical_ohlcv(self.symbol, "1m", days=M1_DAYS),
            "1m",
        )
        signal, result, last_ts = scan_closed_bars(
            signal_rows, m1, self.params, bar_seconds=self.bar_seconds
        )
        return signal, last_ts, result

    def _place_exits(self, lots: int, stop: float, target: float, side: str) -> None:
        tick = self.broker.get_product_tick_size()
        stop = round_to_tick(stop, tick)
        target = round_to_tick(target, tick)
        close_side = _exit_side(side)
        self.broker.place_limit_order(lots, close_side, target, reduce_only=True)
        self.broker.place_stop_order(lots, close_side, stop, reduce_only=True)

    def _enter(self, signal: EntrySignal, dry_run: bool) -> list[str]:
        lots = self.params.position_lots
        partial = _scale_out_lots(lots, self.params.partial_exit_pct)
        runner = lots - partial if partial else 0
        offset = self.params.runner_target_points
        runner_tp = (
            signal.entry_price + offset if signal.side == "long" else signal.entry_price - offset
        )
        mode = "DRY-RUN" if dry_run else "LIVE"
        trade = "BUY" if signal.side == "long" else "SELL"
        tp_lots = _scale_out_lots(lots, self.params.partial_exit_pct) or lots
        actions = _order_log_lines(
            signal,
            mode=mode,
            trade=trade,
            lots=lots,
            tp_lots=tp_lots if runner else lots,
            runner=runner,
            runner_tp=runner_tp,
        )
        mail_lines = [
            "Hammer / Shooting Star — entry signal",
            "",
            *actions,
        ]
        if dry_run:
            self.state.last_entry_ts = signal.entry_ts
            save_state(self.state)
            actions.append(
                _notify(f"[DRY-RUN] {trade} {self.symbol} @ {signal.entry_price:.2f}", mail_lines)
            )
            return actions
        side = "buy" if signal.side == "long" else "sell"
        # PAXGUSD max leverage on Delta is typically 20x (higher values are rejected).
        leverage = float(get_env("DELTA_LEVERAGE", "20") or "20")
        try:
            applied = self.broker.ensure_leverage(leverage)
            actions.append(f"Leverage set to {applied:g}x (requested {leverage:g}x)")
        except Exception as exc:
            actions.append(f"Leverage set failed ({leverage:g}x): {exc}")
            return actions
        self.broker.place_market_order(lots, side)
        fill = self.broker.get_position_entry_price() or signal.entry_price
        stop = signal.stop_loss
        target = (
            fill + self.params.target_points
            if signal.side == "long"
            else fill - self.params.target_points
        )
        runner_tp = fill + offset if signal.side == "long" else fill - offset
        tp_lots = partial or lots
        close_side = _exit_side(signal.side)
        tick = self.broker.get_product_tick_size()
        self.broker.cancel_open_orders()
        self.broker.place_limit_order(
            tp_lots, close_side, round_to_tick(target, tick), reduce_only=True
        )
        self.broker.place_stop_order(
            lots, close_side, round_to_tick(stop, tick), reduce_only=True
        )
        self.state = LiveState(
            last_entry_ts=signal.entry_ts,
            stage="full",
            side=signal.side,
            entry_price=fill,
            stop_loss=stop,
            target=target,
            runner_target=runner_tp,
            lots=lots,
            runner_lots=runner,
        )
        save_state(self.state)
        actions = _order_log_lines(
            signal,
            mode=mode,
            trade=trade,
            lots=lots,
            fill=fill,
            tp_lots=tp_lots,
            runner=runner,
            runner_tp=runner_tp,
            stop=stop,
            target=target,
        )
        mail_lines = [
            "Hammer / Shooting Star — live order filled",
            "",
            *actions,
            "",
            f"Resting limit {tp_lots} lots @ {target:.2f}",
            f"Resting stop {lots} lots @ {stop:.2f}",
        ]
        actions.append(_notify(f"[LIVE] {trade} {self.symbol} {lots} lots @ {fill:.2f}", mail_lines))
        return actions

    def _manage_open(self, dry_run: bool) -> list[str]:
        if dry_run or self.state.stage == "flat" or not self.broker.is_configured:
            return []
        size = abs(self.broker.get_open_position_size())
        if size == 0:
            prev = self.state
            self.broker.cancel_open_orders()
            self.state = LiveState(last_entry_ts=self.state.last_entry_ts)
            save_state(self.state)
            side_label = "BUY/LONG" if prev.side == "long" else "SELL/SHORT" if prev.side else "FLAT"
            kind = "runner close" if prev.stage == "runner" else "position close"
            msg = (
                f"{_utc_now()} | position closed | {side_label} entry {prev.entry_price:.2f} "
                f"stop {prev.stop_loss:.2f} target {prev.target:.2f}"
            )
            mail = _notify(
                f"[LIVE] {kind} {self.symbol} {side_label}",
                [
                    "Hammer / Shooting Star — position closed",
                    "",
                    f"Symbol:  {self.symbol}",
                    f"Side:    {side_label}",
                    f"Stage:   {prev.stage}",
                    f"Entry:   {prev.entry_price:.2f}",
                    f"Stop:    {prev.stop_loss:.2f}",
                    f"Target:  {prev.target:.2f}",
                    f"Runner:  {prev.runner_target:.2f}",
                    "",
                    "Exchange position is now 0. Remaining TP/SL orders were cancelled.",
                ],
            )
            return [msg, mail]
        if self.state.stage == "full" and self.state.runner_lots and size <= self.state.runner_lots:
            self.broker.cancel_open_orders()
            be = self.state.entry_price
            self._place_exits(
                self.state.runner_lots, be, self.state.runner_target, self.state.side
            )
            self.state.stage = "runner"
            self.state.stop_loss = be
            save_state(self.state)
            trade = "BUY" if self.state.side == "long" else "SELL"
            msg = (
                f"{_utc_now()} | 80% TP filled @ {self.state.target:.2f} | "
                f"runner {self.state.runner_lots} lots | BE stop {be:.2f} | "
                f"runner TP {self.state.runner_target:.2f}"
            )
            mail = _notify(
                f"[LIVE] 80% TP {self.symbol} {trade} @ {self.state.target:.2f}",
                [
                    "Hammer / Shooting Star — 80% take-profit filled",
                    "",
                    f"Symbol:     {self.symbol}",
                    f"Side:       {trade}",
                    f"Entry:      {self.state.entry_price:.2f}",
                    f"TP 80%:     {self.state.target:.2f}",
                    f"Runner:     {self.state.runner_lots} lots",
                    f"Runner SL:  {be:.2f} (breakeven)",
                    f"Runner TP:  {self.state.runner_target:.2f}",
                ],
            )
            return [msg, mail]
        return []

    def tick(self, dry_run: bool = True) -> list[str]:
        actions = self._manage_open(dry_run)
        signal, last_ts, result = self.latest_signal()
        actions.append(_status_log(last_ts, result))
        if signal is None:
            return actions
        if signal.entry_ts == self.state.last_entry_ts:
            actions.append("Signal already handled")
            return actions
        exchange_size = 0
        if not dry_run and self.broker.is_configured:
            exchange_size = self.broker.get_open_position_size()
        if not _can_enter(exchange_size, signal.side, self.params.position_lots):
            actions.append(
                f"Skip {signal.side}: exchange size {exchange_size} lots already working"
            )
            return actions
        actions.extend(self._enter(signal, dry_run))
        return actions
