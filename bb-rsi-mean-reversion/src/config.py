"""Fail-fast settings loaded from environment. This bot never reads other strategies' state."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.errors import ConfigError

PACKAGE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PACKAGE_DIR / ".env"
STATE_DIR = PACKAGE_DIR / "data"
LOG_DIR = PACKAGE_DIR / "logs"

TESTNET_REST_URL = "https://cdn-ind.testnet.deltaex.org"
TESTNET_WS_URL = "wss://socket-ind.testnet.deltaex.org"
PROD_INDIA_REST_URL = "https://api.india.delta.exchange"
PROD_INDIA_WS_URL = "wss://socket.india.delta.exchange"

# London shorts on 2 red 1m bars, SL = first red high. US longs on 2 green 1m bars, SL = first green low.

# India clock. New entries only at session opens (not the full London/US day).
# London open 12:30–2:00 PM IST. US/NYSE open 7:00–9:30 PM IST.
LONDON_OPEN_START_MIN_IST = 12 * 60 + 30
LONDON_OPEN_END_MIN_IST = 14 * 60
US_OPEN_START_MIN_IST = 19 * 60
US_OPEN_END_MIN_IST = 21 * 60 + 30
LOSS_COOLDOWN_MINUTES = 15
MAX_SESSION_STOPS = 2

DAILY_TRADE_CAP = 4
DAILY_MAX_LOSS_USD = 14.0
PER_TRADE_STOP_USD = 3.50
TAKE_PROFIT_USD = 10.0
PROFIT_LOCK_USD = 5.0
MAX_PROFIT_USD = 20.0
MIN_PROFIT_USD = 5.0

DEFAULT_CONTRACT_ETH = 0.01  # Delta ETHUSD: 1 lot = 0.01 ETH → 100 lots = 1 ETH
FIXED_LOTS = 100
# Delta India taker ~0.05% of notional per side (entry + exit). Same unit as LQDTY backtest.
TAKER_FEE_PCT = 0.05
CANDLE_LOOKBACK = 80
POLL_SECONDS = 10
WS_RECONNECT_SECONDS = 5
HTTP_MAX_RETRIES = 5


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    api_key: str
    api_secret: str
    rest_url: str
    ws_url: str
    symbol: str
    daily_trade_cap: int
    daily_max_loss_usd: float
    per_trade_stop_usd: float
    take_profit_usd: float
    profit_lock_usd: float
    max_profit_usd: float
    lots: int
    fee_pct_per_side: float
    trail_to_max_profit: bool
    enable_trailing_lock: bool
    net_of_fees: bool
    poll_seconds: int
    dry_run: bool
    loss_cooldown_minutes: int
    max_session_stops: int

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.api_secret)


def websocket_url_for(rest_url: str) -> str:
    url = rest_url.lower()
    if "testnet" in url:
        return TESTNET_WS_URL
    if "india.delta.exchange" in url:
        return PROD_INDIA_WS_URL
    return "wss://socket.delta.exchange"


def load_settings(*, require_keys: bool = True, dry_run: bool = False) -> Settings:
    from dotenv import load_dotenv

    # Parent .env is fallback only; this package's .env wins and is never shared as live state.
    load_dotenv(PACKAGE_DIR.parent / ".env")
    load_dotenv(ENV_FILE, override=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    api_key = os.getenv("DELTA_API_KEY", "").strip()
    api_secret = os.getenv("DELTA_API_SECRET", "").strip()
    if require_keys and (not api_key or not api_secret):
        raise ConfigError("DELTA_API_KEY and DELTA_API_SECRET must be set in .env")

    rest_url = os.getenv("DELTA_BASE_URL", TESTNET_REST_URL).strip().rstrip("/")
    ws_override = os.getenv("DELTA_WS_URL", "").strip()
    settings = Settings(
        api_key=api_key,
        api_secret=api_secret,
        rest_url=rest_url,
        ws_url=ws_override or websocket_url_for(rest_url),
        symbol=os.getenv("DELTA_SYMBOL", "ETHUSD").strip() or "ETHUSD",
        daily_trade_cap=_env_int("DAILY_TRADE_CAP", DAILY_TRADE_CAP),
        daily_max_loss_usd=_env_float("DAILY_MAX_LOSS_USD", DAILY_MAX_LOSS_USD),
        per_trade_stop_usd=_env_float("PER_TRADE_STOP_USD", PER_TRADE_STOP_USD),
        take_profit_usd=_env_float("TAKE_PROFIT_USD", TAKE_PROFIT_USD),
        profit_lock_usd=_env_float("PROFIT_LOCK_USD", PROFIT_LOCK_USD),
        max_profit_usd=_env_float("MAX_PROFIT_USD", MAX_PROFIT_USD),
        lots=_env_int("FIXED_LOTS", FIXED_LOTS),
        fee_pct_per_side=_env_float("FEE_PCT_PER_SIDE", TAKER_FEE_PCT),
        trail_to_max_profit=_env_bool("TRAIL_TO_MAX_PROFIT", False),
        enable_trailing_lock=_env_bool("ENABLE_TRAILING_LOCK", False),
        net_of_fees=_env_bool("NET_TARGETS_OF_FEES", True),
        poll_seconds=_env_int("POLL_SECONDS", POLL_SECONDS),
        dry_run=dry_run,
        loss_cooldown_minutes=_env_int("LOSS_COOLDOWN_MINUTES", LOSS_COOLDOWN_MINUTES),
        max_session_stops=_env_int("MAX_SESSION_STOPS", MAX_SESSION_STOPS),
    )
    if settings.take_profit_usd < MIN_PROFIT_USD or settings.take_profit_usd > MAX_PROFIT_USD:
        raise ConfigError(
            f"TAKE_PROFIT_USD must be between {MIN_PROFIT_USD} and {MAX_PROFIT_USD}"
        )
    return settings
