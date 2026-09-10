"""Persisted state for the ETH India volume-bias live runner."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import get_env
from src.timezone import format_india_timestamp


def known_fields(cls: type, raw: dict[str, Any]) -> dict[str, Any]:
    allowed = {item.name for item in fields(cls)}
    return {key: value for key, value in raw.items() if key in allowed}


def env_int(name: str, default: int) -> int:
    raw = get_env(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def env_float(name: str, default: float) -> float:
    raw = get_env(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass
class LivePositionState:
    side: str
    entry_price: float
    stop_loss: float
    target: float
    entry_ts: str
    entry_lots: int
    pullback_high: float
    pullback_low: float
    initial_stop_loss: float = 0.0


@dataclass
class LiveSessionState:
    day: str = ""
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    bias: str = ""
    bias_locked: bool = False
    pullback: dict[str, float | str] | None = None
    traded_today: bool = False
    wins_today: int = 0
    losses_today: int = 0
    after_pullback_ts: str = ""
    last_processed_ts: str = ""


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
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    bias: str = ""
    exchange_position: int = 0
    in_position: bool = False
    error: str = ""


def load_strategy_state(path: Path, symbol: str) -> LiveStrategyState:
    if not path.exists():
        return LiveStrategyState(symbol=symbol)
    raw = json.loads(path.read_text(encoding="utf-8"))
    session = LiveSessionState(**known_fields(LiveSessionState, raw.pop("session", {})))
    position_raw = raw.pop("position", None)
    position = None
    if position_raw:
        position = LivePositionState(**known_fields(LivePositionState, position_raw))
    return LiveStrategyState(
        session=session,
        position=position,
        **known_fields(LiveStrategyState, raw),
    )


def save_strategy_state(path: Path, state: LiveStrategyState) -> None:
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def append_log(state: LiveStrategyState, message: str) -> None:
    stamp = format_india_timestamp(datetime.now(timezone.utc).isoformat())
    state.logs.append(f"[{stamp}] {message}")
    state.logs = state.logs[-100:]
