from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_DIR / ".env"
DATA_DIR = PROJECT_DIR / "data"
STRATEGIES_DIR = DATA_DIR / "strategies"
LIVE_STATE_DIR = DATA_DIR / "live"

load_dotenv(ENV_FILE)


def ensure_data_dirs() -> None:
    for directory in (STRATEGIES_DIR, LIVE_STATE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def get_env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()
