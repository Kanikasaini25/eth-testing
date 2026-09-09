from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.backtest import BacktestParams, bar_seconds_for_resolution, run_pattern_backtest
from src.config import PROJECT_DIR, get_env
from src.delta_data import closed_ohlcv
from src.mt5_broker import Mt5Broker
from src.product_specs import backtest_params_from_env
from src.strategy import EntrySignal

MT5_STATE_PATH = PROJECT_DIR / "data" / "live" / "mt5_pattern_state.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def mt5_live_params(volume: float | None = None) -> BacktestParams:
    params = backtest_params_from_env(get_env("DELTA_SYMBOL", "ETHUSD"))
    # MT5 uses broker lots (0.01 etc). Keep target/SL logic in price points.
    if volume is not None:
        params.position_lots = max(1, int(round(volume * 100)))  # store as cents-of-lot for state
    return params


@dataclass
class Mt5LiveState:
    last_entry_ts: str = ""
    side: str = ""
    volume: float = 0.0
    original_volume: float = 0.0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    target_1: float = 0.0
    target_2: float = 0.0
    target_3: float = 0.0
    target_4: float = 0.0
    target_5: float = 0.0
    targets_hit: int = 0
    pattern_ts: str = ""


def _load_state() -> Mt5LiveState:
    if not MT5_STATE_PATH.exists():
        return Mt5LiveState()
    try:
        data = json.loads(MT5_STATE_PATH.read_text())
        return Mt5LiveState(**{k: data[k] for k in Mt5LiveState.__dataclass_fields__ if k in data})
    except Exception:
        return Mt5LiveState()


def _save_state(state: Mt5LiveState) -> None:
    MT5_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    MT5_STATE_PATH.write_text(json.dumps(asdict(state), indent=2))


def _signal_on_last_bar(
    signal_rows: list[dict],
    m1_rows: list[dict],
    params: BacktestParams,
    bar_seconds: int,
) -> EntrySignal | None:
    entries: list[EntrySignal] = []
    run_pattern_backtest(
        signal_rows,
        m1_rows,
        params,
        bar_seconds=bar_seconds,
        entry_log=entries,
    )
    if not entries or not m1_rows:
        return None
    last_ts = m1_rows[-1]["timestamp"]
    return entries[-1] if entries[-1].entry_ts == last_ts else None


def _target_ladder(entry: float, side: str, step: float) -> tuple[float, float, float, float, float]:
    signs = (1, 2, 3, 4, 5) if side == "long" else (-1, -2, -3, -4, -5)
    return tuple(entry + s * step for s in signs)  # type: ignore[return-value]


def _scale_vol(original: float, remaining: float, pct: float, step: float) -> float:
    desired = round(original * pct / 100.0, 2)
    desired = max(step, desired)
    # leave a crumb for later targets when possible
    if remaining - desired < step and remaining > step:
        desired = remaining - step
    return min(desired, remaining)


class Mt5PatternRunner:
    """Hammer / Shooting Star live runner for local MT5 (PDMBulls demo/live)."""

    def __init__(
        self,
        *,
        broker: Mt5Broker | None = None,
        params: BacktestParams | None = None,
        candle_resolution: str | None = None,
        volume: float | None = None,
    ) -> None:
        self.broker = broker or Mt5Broker()
        self.params = params or mt5_live_params()
        self.candle_resolution = (
            candle_resolution or get_env("MT5_CANDLE", "15m") or "15m"
        ).strip()
        self.volume = float(volume if volume is not None else (get_env("MT5_VOLUME", "0.10") or "0.10"))
        self.state = _load_state()

    def _manage_open_trade(self, dry_run: bool) -> list[str]:
        actions: list[str] = []
        open_vol = self.broker.position_volume()
        if open_vol <= 0:
            if self.state.side:
                actions.append(f"{_utc_now()} | position closed externally — clearing state")
                self.state = Mt5LiveState()
                _save_state(self.state)
            return actions

        tick_rows = self.broker.fetch_ohlcv("1m", bars=3)
        last = tick_rows[-1]
        high = float(last["high"])
        low = float(last["low"])
        side = self.state.side or self.broker.position_side()
        step = abs(self.state.target_1 - self.state.entry_price) if self.state.target_1 else self.params.target_points
        t1, t2, t3, t4, t5 = _target_ladder(
            self.state.entry_price, side, step or self.params.target_points
        )
        targets = (t1, t2, t3, t4, t5)
        level = self.state.targets_hit + 1
        if level < 1 or level > 5:
            return actions
        target = targets[level - 1]
        hit = (side == "long" and high >= target) or (side == "short" and low <= target)
        if not hit:
            return actions

        step_vol = self.broker.volume_step()
        original = self.state.original_volume or open_vol
        pcts = getattr(self.params, "exit_scale_pcts", (30.0, 40.0, 10.0, 10.0))

        if level >= 5:
            close_vol = open_vol
            label = "T5"
        else:
            close_vol = _scale_vol(original, open_vol, float(pcts[level - 1]), step_vol)
            label = f"T{level}"

        if dry_run:
            actions.append(f"{_utc_now()} | DRY {label} — would close {close_vol}")
        else:
            self.broker.close_partial(close_vol)
            actions.append(f"{_utc_now()} | LIVE {label} — closed {close_vol}")

        if level >= 5 or close_vol >= open_vol - 1e-9:
            self.state = Mt5LiveState()
            _save_state(self.state)
            return actions

        self.state.targets_hit = level
        self.state.volume = max(0.0, open_vol - close_vol)
        # SL trail: T1 mid, T2→T1, T3→T3, T4→T4
        if level == 1:
            self.state.stop_loss = (self.state.entry_price + t1) / 2.0
            new_tp = t2
        elif level == 2:
            self.state.stop_loss = t1
            new_tp = t3
        elif level == 3:
            self.state.stop_loss = t3
            new_tp = t4
        else:  # level == 4
            self.state.stop_loss = t4
            new_tp = t5
        if not dry_run:
            self.broker.modify_position_sl_tp(stop_loss=self.state.stop_loss, take_profit=new_tp)
        actions.append(f"  trailed SL → {self.state.stop_loss:.2f} · next TP → {new_tp:.2f}")
        _save_state(self.state)
        return actions

    def tick(self, *, dry_run: bool = True) -> list[str]:
        lines: list[str] = []
        signal_bars = int(get_env("MT5_SIGNAL_BARS", "400") or "400")
        m1_bars = int(get_env("MT5_M1_BARS", "1500") or "1500")

        signal_rows = closed_ohlcv(
            self.broker.fetch_ohlcv(self.candle_resolution, bars=signal_bars),
            self.candle_resolution if self.candle_resolution != "45m" else "30m",
        )
        m1_rows = closed_ohlcv(self.broker.fetch_ohlcv("1m", bars=m1_bars), "1m")
        last_close = float(m1_rows[-1]["close"]) if m1_rows else 0.0
        lines.append(
            f"{_utc_now()} | MT5 {self.broker.symbol} @ {self.broker.server} · "
            f"{self.candle_resolution} bars={len(signal_rows)} · 1m={len(m1_rows)} · last {last_close:.2f}"
        )

        if self.broker.position_volume() > 0 or self.state.side:
            lines.extend(self._manage_open_trade(dry_run=dry_run))
            if self.broker.position_volume() > 0:
                lines.append(f"  open position {self.broker.position_volume()} lots — waiting")
                return lines

        bar_seconds = bar_seconds_for_resolution(
            self.candle_resolution if self.candle_resolution != "45m" else "30m"
        )
        signal = _signal_on_last_bar(signal_rows, m1_rows, self.params, bar_seconds)
        if signal is None:
            lines.append("  no new Hammer/Shooting Star confirmation")
            return lines
        if signal.entry_ts == self.state.last_entry_ts:
            lines.append(f"  already acted on {signal.entry_ts}")
            return lines

        trade = "BUY" if signal.side == "long" else "SELL"
        step = abs(signal.target - signal.entry_price)
        t1, t2, t3, t4, t5 = _target_ladder(signal.entry_price, signal.side, step)
        lines.append(f"{_utc_now()} | SIGNAL {trade} {self.volume} lots")
        lines.append(f"  pattern: {signal.grab_ts} · entry {signal.entry_price:.2f}")
        lines.append(
            f"  SL {signal.stop_loss:.2f} · T1 {t1:.2f} · T2 {t2:.2f} · "
            f"T3 {t3:.2f} · T4 {t4:.2f} · T5 {t5:.2f}"
        )

        if dry_run:
            lines.append("  DRY-RUN — no order sent (add --live to trade on PDMBulls demo)")
            self.state.last_entry_ts = signal.entry_ts
            _save_state(self.state)
            return lines

        result = self.broker.place_market(
            signal.side,
            self.volume,
            stop_loss=signal.stop_loss,
            take_profit=t1,
            comment=f"{signal.side[:1].upper()}pat",
        )
        fill = float(result.get("price") or signal.entry_price)
        self.state = Mt5LiveState(
            last_entry_ts=signal.entry_ts,
            side=signal.side,
            volume=self.volume,
            original_volume=self.volume,
            entry_price=fill,
            stop_loss=signal.stop_loss,
            target_1=t1,
            target_2=t2,
            target_3=t3,
            target_4=t4,
            target_5=t5,
            targets_hit=0,
            pattern_ts=signal.grab_ts,
        )
        _save_state(self.state)
        lines.append(f"  LIVE ORDER filled @ {fill:.2f} · ticket {result.get('order')}")
        return lines
