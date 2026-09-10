from __future__ import annotations

import os
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone

import requests

CANDLES_PER_REQUEST = 2000
SECONDS_PER_DAY = 86400

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


class DeltaExchangeClient:
    def __init__(self, base_url: str = "https://api.india.delta.exchange") -> None:
        self.base_url = base_url.rstrip("/")
        self.http_client = requests.Session()
        self.http_client.trust_env = (
            os.getenv("DELTA_USE_ENV_PROXY", "false").lower() == "true"
        )

    def fetch_candles(
        self,
        symbol: str,
        resolution: str,
        start: int,
        end: int,
    ) -> list[dict]:
        response = self.http_client.get(
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
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        if end_date is None:
            end = int(time.time())
        else:
            end_datetime = datetime.combine(
                end_date + timedelta(days=1),
                datetime_time.min,
                tzinfo=timezone.utc,
            )
            end = int(end_datetime.timestamp())
        if start_date is None:
            start = end - (days * SECONDS_PER_DAY)
        else:
            start_datetime = datetime.combine(
                start_date,
                datetime_time.min,
                tzinfo=timezone.utc,
            )
            start = int(start_datetime.timestamp())
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

    def fetch_mark_price(self, symbol: str) -> float:
        """Public ticker mark price (no auth). Used for India-live signal following."""
        response = self.http_client.get(
            f"{self.base_url}/v2/tickers/{symbol}",
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            raise RuntimeError(f"Delta Exchange ticker error: {payload}")
        result = payload.get("result") or {}
        mark_price = result.get("mark_price") or result.get("spot_price")
        if mark_price is None:
            raise RuntimeError(f"Could not fetch mark price for {symbol} from {self.base_url}")
        return float(mark_price)
