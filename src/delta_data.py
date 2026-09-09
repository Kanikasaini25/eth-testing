from __future__ import annotations

import time
from datetime import datetime, timezone

import requests

from src.config import get_candle_base_url

CANDLES_PER_REQUEST = 2000
SECONDS_PER_DAY = 86400

RESOLUTION_SECONDS: dict[str, int] = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "45m": 2700,
    "1h": 3600,
    "2h": 7200,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}


class DeltaExchangeClient:
    def __init__(self, base_url: str | None = None) -> None:
        resolved = (base_url or get_candle_base_url()).rstrip("/")
        if "testnet" in resolved.lower():
            raise ValueError(
                "Testnet candle data is not allowed. "
                f"Use India live: {get_candle_base_url()}"
            )
        self.base_url = resolved

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
            headers={
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
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
        days: int = 30,
        on_progress=None,
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
            if on_progress is not None:
                fetched_days = (end - min(item["time"] for item in batch)) / SECONDS_PER_DAY
                on_progress(min(days, fetched_days), days, resolution)
            earliest = min(item["time"] for item in batch)
            if earliest <= start or len(batch) < 2:
                break
            chunk_end = earliest - 1
            time.sleep(0.15)

        if not all_candles:
            raise RuntimeError(f"No candle data returned for {symbol}")

        rows: list[dict] = []
        seen: set[int] = set()
        for candle in sorted(all_candles, key=lambda item: item["time"]):
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

    def fetch_historical_ohlcv_range(
        self,
        symbol: str,
        resolution: str = "1d",
        start: int | None = None,
        end: int | None = None,
        on_progress=None,
    ) -> list[dict]:
        if start is None or end is None or start >= end:
            raise ValueError("start and end must be valid unix timestamps with start < end")

        seconds_per_candle = RESOLUTION_SECONDS.get(resolution, SECONDS_PER_DAY)
        chunk_seconds = CANDLES_PER_REQUEST * seconds_per_candle
        total_days = max((end - start) / SECONDS_PER_DAY, 1.0)

        all_candles: list[dict] = []
        chunk_end = end

        while chunk_end > start:
            chunk_start = max(start, chunk_end - chunk_seconds)
            batch = self.fetch_candles(symbol, resolution, chunk_start, chunk_end)
            if not batch:
                break

            all_candles.extend(batch)
            if on_progress is not None:
                fetched_days = (end - min(item["time"] for item in batch)) / SECONDS_PER_DAY
                on_progress(min(total_days, fetched_days), total_days, resolution)
            earliest = min(item["time"] for item in batch)
            if earliest <= start or len(batch) < 2:
                break
            chunk_end = earliest - 1
            time.sleep(0.15)

        if not all_candles:
            raise RuntimeError(f"No candle data returned for {symbol}")

        rows: list[dict] = []
        seen: set[int] = set()
        for candle in sorted(all_candles, key=lambda item: item["time"]):
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


def closed_ohlcv(
    rows: list[dict],
    resolution: str,
    now: float | None = None,
) -> list[dict]:
    """Drop the in-progress candle so live scans match the backtest (closed bars only)."""
    now_ts = time.time() if now is None else now
    seconds = RESOLUTION_SECONDS.get(resolution, SECONDS_PER_DAY)
    out: list[dict] = []
    for row in rows:
        start = datetime.fromisoformat(row["timestamp"]).timestamp()
        if start + seconds <= now_ts:
            out.append(row)
    return out
