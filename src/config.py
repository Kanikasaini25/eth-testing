from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
DATA_DIR = PROJECT_DIR / "data"
OHLCV_DIR = DATA_DIR / "ohlcv"
STRATEGIES_DIR = DATA_DIR / "strategies"
REPORTS_DIR = DATA_DIR / "reports"
LIVE_STATE_DIR = DATA_DIR / "live"

# Real India ETHUSD history for backtests. Demo/live orders still use DELTA_BASE_URL.
DELTA_BACKTEST_BASE_URL = "https://api.india.delta.exchange"

load_dotenv(ENV_FILE)


def ensure_data_dirs() -> None:
    for directory in (OHLCV_DIR, STRATEGIES_DIR, REPORTS_DIR, LIVE_STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
