from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
LIVE_STATE_PATH = PROJECT_DIR / "data" / "live" / "liquidity_grab_state.json"

# India production — all candle/backtest data must use this (never testnet).
INDIA_LIVE_URL = "https://api.india.delta.exchange"


def reload_env(*, override: bool = True) -> None:
    """Load `.env` into os.environ. Use override so Streamlit picks up edits."""
    load_dotenv(PROJECT_DIR / ".env", override=override)


reload_env(override=False)


def get_candle_base_url() -> str:
    """Historical OHLCV always comes from India live production."""
    return INDIA_LIVE_URL


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
