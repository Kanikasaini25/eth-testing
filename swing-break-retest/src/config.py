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

load_dotenv(ENV_FILE)


def ensure_data_dirs() -> None:
    for directory in (OHLCV_DIR, STRATEGIES_DIR, REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
