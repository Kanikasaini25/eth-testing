from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
LIVE_STATE_DIR = PROJECT_DIR / "data" / "live"

STRATEGY_FUNDING = "funding"
STRATEGIES = (STRATEGY_FUNDING,)


@dataclass(frozen=True)
class SymbolSpec:
    """One tradable funding book: the perp, its INR spot hedge, and lot size."""

    futures: str
    spot: str
    contract_value: float


SYMBOL_SPECS: dict[str, SymbolSpec] = {
    "ETHUSD": SymbolSpec("ETHUSD", "ETH_INR", 0.01),
    "BTCUSD": SymbolSpec("BTCUSD", "BTC_INR", 0.001),
    "SOLUSD": SymbolSpec("SOLUSD", "SOL_INR", 1.0),
    "XRPUSD": SymbolSpec("XRPUSD", "XRP_INR", 1.0),
}

# ETH and BTC funding sat one-sided ~78% of the last year and traded 3-4 times.
# SOL was 54% (a coin flip), churned 120 times and lost money on fees.
DEFAULT_SYMBOLS = ("ETHUSD", "BTCUSD")
MIN_ONE_SIDED_SHARE = 0.75
DEFAULT_NOTIONAL_USD = 2450.0

FIXED_LOTS = 100
ETH_CONTRACT_VALUE = SYMBOL_SPECS["ETHUSD"].contract_value


def symbol_spec(symbol: str) -> SymbolSpec:
    """Known books get their real lot size; anything else defaults to 1 unit."""
    key = symbol.strip().upper()
    known = SYMBOL_SPECS.get(key)
    if known is not None:
        return known
    base = key[:-3] if key.endswith("USD") else key
    return SymbolSpec(key, f"{base}_INR", 1.0)


def lots_for_notional(symbol: str, price: float, notional_usd: float) -> int:
    if price <= 0:
        raise ValueError(f"Price must be positive to size {symbol}")
    per_lot = symbol_spec(symbol).contract_value * price
    return max(1, round(notional_usd / per_lot))


def parse_symbols(raw: str) -> tuple[str, ...]:
    parsed = tuple(item.strip().upper() for item in raw.split(",") if item.strip())
    return parsed or DEFAULT_SYMBOLS

# Display and live hourly buckets. Exchange funding prints stay UTC 00/08/16.
APP_TZ = ZoneInfo("Asia/Kolkata")
APP_TZ_NAME = "Asia/Kolkata"


def get_env(name: str, default: str = "") -> str:
    value = os.getenv(name, default).strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def get_env_bool(name: str, default: bool = False) -> bool:
    raw = get_env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def get_env_int(name: str, default: int) -> int:
    raw = get_env(name)
    return int(raw) if raw else default


def get_env_float(name: str, default: float) -> float:
    raw = get_env(name)
    return float(raw) if raw else default


def live_state_path(strategy: str, symbol: str = "") -> Path:
    """Each symbol keeps its own state so books never overwrite each other."""
    if not symbol:
        return LIVE_STATE_DIR / f"{strategy}_state.json"
    return LIVE_STATE_DIR / f"{strategy}_{symbol.strip().upper()}_state.json"


def now_ist() -> datetime:
    return datetime.now(APP_TZ)


def to_ist(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(APP_TZ)


def format_ist(value: str | datetime) -> str:
    return to_ist(value).strftime("%Y-%m-%d %H:%M:%S IST")
