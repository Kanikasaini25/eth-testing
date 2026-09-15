"""Download India-live ETHUSD candles once and keep them on disk for sweeps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from src.config import get_market_data_base_url
from src.delta_data import fetch_closed_ohlcv

CACHE_DIR = PROJECT_DIR / "data" / "ohlcv"


def cache_path(symbol: str, resolution: str) -> Path:
    return CACHE_DIR / f"{symbol}_{resolution}_india.json"


def load_cached(symbol: str, resolution: str) -> list[dict]:
    path = cache_path(symbol, resolution)
    if not path.exists():
        raise FileNotFoundError(
            f"No cached {resolution} candles at {path}. Run scripts/cache_history.py first."
        )
    return json.loads(path.read_text())


def download(symbol: str, resolution: str, days: int) -> list[dict]:
    def on_progress(fetched: float, total: int, res: str) -> None:
        print(f"  {res}: {fetched:.1f}/{total} days", flush=True)

    rows = fetch_closed_ohlcv(
        symbol=symbol,
        resolution=resolution,
        days=days,
        on_progress=on_progress,
        base_url=get_market_data_base_url(),
    )
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(symbol, resolution).write_text(json.dumps(rows))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSD")
    parser.add_argument("--days", type=int, default=180)
    args = parser.parse_args()

    print(f"Feed: {get_market_data_base_url()}")
    for resolution in ("15m", "1m"):
        rows = download(args.symbol, resolution, args.days)
        print(
            f"{resolution}: {len(rows)} closed candles "
            f"{rows[0]['timestamp']} -> {rows[-1]['timestamp']}",
            flush=True,
        )


if __name__ == "__main__":
    main()
