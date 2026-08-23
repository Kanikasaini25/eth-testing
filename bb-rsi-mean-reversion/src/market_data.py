"""Public historical 1m candles for backtests. No API keys required."""

from __future__ import annotations

import csv
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from src.config import STATE_DIR
from src.errors import DeltaAPIError
from src.http import DeltaHttp
from src.session import utc_day

CANDLES_PER_REQUEST = 2000
SECONDS_PER_DAY = 86400
CANDLES_PER_DAY_1M = 1440
OHLCV_DIR = STATE_DIR / "ohlcv"


ProgressFn = Callable[[str], None]


def expected_1m_candles(days: int) -> int:
    return max(days, 0) * CANDLES_PER_DAY_1M


def _cache_path(symbol: str, days: int, base_url: str) -> Path:
    host = base_url.replace("https://", "").replace("http://", "").replace("/", "_")
    return OHLCV_DIR / f"{symbol}_1m_{days}d_{utc_day()}_{host}.csv"


def _rows_from_raw(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    for candle in sorted(raw or [], key=lambda item: item["time"]):
        ts = int(candle["time"])
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
                "volume": float(candle.get("volume") or 0),
            }
        )
    return rows


def save_ohlcv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def load_ohlcv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def fetch_historical_1m(
    *,
    symbol: str,
    days: int,
    base_url: str,
    use_cache: bool = True,
    progress: ProgressFn | None = None,
) -> list[dict[str, Any]]:
    OHLCV_DIR.mkdir(parents=True, exist_ok=True)
    cache = _cache_path(symbol, days, base_url)
    if use_cache and cache.exists():
        if progress:
            progress(f"Loaded cached 1m candles from {cache.name}")
        rows = load_ohlcv(cache)
        expected = expected_1m_candles(days)
        return rows[-expected:] if len(rows) > expected else rows

    http = DeltaHttp(base_url)
    end = int(time.time())
    start = end - (days * SECONDS_PER_DAY)
    chunk_seconds = CANDLES_PER_REQUEST * 60
    all_raw: list[dict[str, Any]] = []
    chunk_end = end

    while chunk_end > start:
        chunk_start = max(start, chunk_end - chunk_seconds)
        if progress:
            progress(f"Fetching 1m candles {chunk_start} → {chunk_end}")
        batch = http.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": symbol,
                "resolution": "1m",
                "start": chunk_start,
                "end": chunk_end,
            },
        )
        if not batch:
            break
        all_raw.extend(batch)
        earliest = min(int(item["time"]) for item in batch)
        if earliest <= start or len(batch) < 2:
            break
        chunk_end = earliest - 1
        time.sleep(0.15)

    if not all_raw:
        raise DeltaAPIError(f"No 1m candle data returned for {symbol}")

    rows = _rows_from_raw(all_raw)
    expected = expected_1m_candles(days)
    if len(rows) > expected:
        rows = rows[-expected:]
    save_ohlcv(rows, cache)
    return rows
