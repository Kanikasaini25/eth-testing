from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
LIVE_STATE_PATH = PROJECT_DIR / "data" / "live" / "liquidity_grab_state.json"
INDIA_LIVE_DATA_URL = "https://api.india.delta.exchange"
DEMO_TRADE_URL = "https://cdn-ind.testnet.deltaex.org"


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


def get_market_data_base_url() -> str:
    """Public India-live candles used for signals and backtests."""
    return get_env("DELTA_DATA_BASE_URL", INDIA_LIVE_DATA_URL) or INDIA_LIVE_DATA_URL


def get_trade_base_url() -> str:
    """Authenticated order endpoint. Defaults to the India demo/testnet."""
    return get_env("DELTA_BASE_URL", DEMO_TRADE_URL) or DEMO_TRADE_URL
