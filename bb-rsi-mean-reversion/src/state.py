"""Rolling IST daily PnL / trade-count state. Isolated file — never shares LQDTY state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config import STATE_DIR, Settings
from src.session import in_loss_cooldown, next_ist_midnight, parse_bar_time, session_key, trading_day, utc_now


@dataclass
class OpenPosition:
    side: str
    entry_price: float
    lots: int
    stop_price: float
    take_profit_price: float
    profit_lock_price: float
    max_profit_price: float
    contract_eth: float
    entry_ts: str
    profit_locked: bool = False
    entry_order_id: int | None = None


@dataclass
class DailyState:
    trading_day: str = ""
    realized_pnl: float = 0.0
    trades_taken: int = 0
    kill_switch: bool = False
    last_candle_ts: str = ""
    last_loss_ts: str = ""
    session_key: str = ""
    session_sl_count: int = 0
    session_profit_taken: bool = False
    position: OpenPosition | None = None
    closed_trades: list[dict[str, Any]] = field(default_factory=list)


class DailyTracker:
    def __init__(self, settings: Settings, path: Path | None = None) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.path = path or STATE_DIR / f"{settings.symbol}_bb_rsi_state.json"
        self.state = self._load()

    def _load(self) -> DailyState:
        if not self.path.exists():
            return DailyState(trading_day=trading_day())
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        position_raw = raw.pop("position", None)
        position = OpenPosition(**position_raw) if position_raw else None
        day = raw.pop("trading_day", None) or raw.pop("utc_day", trading_day())
        raw.pop("utc_day", None)
        return DailyState(position=position, trading_day=day, **raw)

    def save(self) -> None:
        payload = asdict(self.state)
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def roll_trading_day(self, now: datetime) -> bool:
        """Reset counters at 00:00 IST. Open position is kept across the day boundary."""
        today = trading_day(now)
        if self.state.trading_day == today:
            return False
        open_position = self.state.position
        last_ts = self.state.last_candle_ts
        last_loss = self.state.last_loss_ts
        self.state = DailyState(
            trading_day=today,
            position=open_position,
            last_candle_ts=last_ts,
            last_loss_ts=last_loss,
        )
        self.save()
        return True

    def roll_utc_day(self, now: datetime) -> bool:
        return self.roll_trading_day(now)

    def halted(self, now: datetime) -> bool:
        return self.state.kill_switch and self.state.trading_day == trading_day(now)

    def refresh_session(self, now: datetime) -> None:
        key = session_key(now)
        if key == self.state.session_key:
            return
        self.state.session_key = key
        self.state.session_sl_count = 0
        self.state.session_profit_taken = False
        self.save()

    def can_take_trade(self, now: datetime | None = None) -> bool:
        stamp = now or utc_now()
        if self.state.kill_switch:
            return False
        if self.state.position is not None:
            return False
        if self.in_loss_cooldown(stamp):
            return False
        self.refresh_session(stamp)
        if not self.state.session_key:
            return False
        if self.state.session_profit_taken:
            return False
        if self.state.session_sl_count >= self.settings.max_session_stops:
            return False
        return self.state.trades_taken < self.settings.daily_trade_cap

    def in_loss_cooldown(self, now: datetime) -> bool:
        return in_loss_cooldown(
            self.state.last_loss_ts,
            now,
            self.settings.loss_cooldown_minutes,
        )

    def daily_pnl(self, unrealized: float = 0.0) -> float:
        return self.state.realized_pnl + unrealized

    def should_kill(self, unrealized: float = 0.0) -> bool:
        return self.daily_pnl(unrealized) <= -abs(self.settings.daily_max_loss_usd)

    def record_entry(self, position: OpenPosition) -> None:
        self.state.position = position
        self.state.trades_taken += 1
        self.save()

    def record_exit(
        self, *, exit_price: float, pnl_usd: float, reason: str, exit_ts: str | None = None
    ) -> None:
        position = self.state.position
        if position is None:
            return
        stamp = exit_ts or utc_now().isoformat()
        self.refresh_session(parse_bar_time(stamp))
        self.state.closed_trades.append(
            {
                "side": position.side,
                "entry": position.entry_price,
                "exit": exit_price,
                "lots": position.lots,
                "pnl": round(pnl_usd, 4),
                "reason": reason,
                "entry_ts": position.entry_ts,
                "exit_ts": stamp,
            }
        )
        self.state.realized_pnl = round(self.state.realized_pnl + pnl_usd, 4)
        self.state.position = None
        if pnl_usd < 0:
            self.state.last_loss_ts = position.entry_ts
            if reason == "stop_loss":
                self.state.session_sl_count += 1
        elif pnl_usd > 0:
            self.state.session_profit_taken = True
        if self.should_kill():
            self.state.kill_switch = True
        self.save()

    def trip_kill_switch(self) -> None:
        self.state.kill_switch = True
        self.save()

    def halt_until_label(self, now: datetime) -> str:
        nxt = next_ist_midnight(now)
        return nxt.strftime("%Y-%m-%d 12:30 IST")
