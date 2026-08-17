from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CANDLES_PER_REQUEST = 2000
SECONDS_PER_DAY = 86400
CANDLES_PER_DAY_1M = 1440
MAX_BACKTEST_DAYS = 365

RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "6h": 21600,
    "1d": 86400,
}


def expected_1m_candles(days: int) -> int:
    """One trading day on 1m timeframe = 1440 candles (24 × 60)."""
    return max(days, 0) * CANDLES_PER_DAY_1M


def trim_ohlcv_to_days(rows: list[dict], days: int, resolution: str = "1m") -> list[dict]:
    if not rows or resolution != "1m":
        return rows
    expected = expected_1m_candles(days)
    if len(rows) > expected:
        return rows[-expected:]
    return rows


class DeltaExchangeClient:
    def __init__(self, base_url: str = "https://api.india.delta.exchange") -> None:
        self.base_url = base_url.rstrip("/")

    def fetch_candles(
        self,
        symbol: str,
        resolution: str,
        start: int,
        end: int,
    ) -> list[dict]:
        response = requests.get(
            f"{self.base_url}/v2/history/candles",
            params={
                "symbol": symbol,
                "resolution": resolution,
                "start": start,
                "end": end,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        if not payload.get("success"):
            raise RuntimeError(f"Delta Exchange API error: {payload}")

        return payload.get("result", [])

    def fetch_historical_ohlcv(
        self,
        symbol: str,
        resolution: str = "1d",
        days: int = 730,
    ) -> list[dict]:
        end = int(time.time())
        start = end - (days * SECONDS_PER_DAY)
        seconds_per_candle = RESOLUTION_SECONDS.get(resolution, SECONDS_PER_DAY)
        chunk_seconds = CANDLES_PER_REQUEST * seconds_per_candle

        all_candles: list[dict] = []
        chunk_end = end

        while chunk_end > start:
            chunk_start = max(start, chunk_end - chunk_seconds)
            batch = self.fetch_candles(symbol, resolution, chunk_start, chunk_end)
            if not batch:
                break

            all_candles.extend(batch)
            earliest = min(item["time"] for item in batch)
            if earliest <= start or len(batch) < 2:
                break
            chunk_end = earliest - 1
            time.sleep(0.15)

        candles = all_candles

        if not candles:
            raise RuntimeError(f"No candle data returned for {symbol}")

        rows: list[dict] = []
        seen: set[int] = set()
        for candle in sorted(candles, key=lambda item: item["time"]):
            ts = candle["time"]
            if ts in seen:
                continue
            seen.add(ts)
            rows.append(
                {
                    "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                    "volume": float(candle["volume"]),
                }
            )

        return rows


def save_ohlcv(rows: list[dict], path: str) -> None:
    if not rows:
        return
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def load_ohlcv(path: str) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
