"""Public historical 5m candles for backtests. No API keys required. Never cached."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from src.config import BAR_SECONDS, CANDLE_RESOLUTION, CANDLES_PER_DAY
from src.errors import DeltaAPIError
from src.http import DeltaHttp

CANDLES_PER_REQUEST = 2000
SECONDS_PER_DAY = 86400


ProgressFn = Callable[[str], None]


def expected_1m_candles(days: int) -> int:
    return max(days, 0) * CANDLES_PER_DAY


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


def fetch_historical_1m(
    *,
    symbol: str,
    days: int,
    base_url: str,
    progress: ProgressFn | None = None,
) -> list[dict[str, Any]]:
    http = DeltaHttp(base_url)
    end = int(time.time())
    start = end - (days * SECONDS_PER_DAY)
    chunk_seconds = CANDLES_PER_REQUEST * BAR_SECONDS
    all_raw: list[dict[str, Any]] = []
    chunk_end = end

    while chunk_end > start:
        chunk_start = max(start, chunk_end - chunk_seconds)
        if progress:
            progress(f"Fetching {CANDLE_RESOLUTION} candles {chunk_start} → {chunk_end}")
        batch = http.request(
            "GET",
            "/v2/history/candles",
            params={
                "symbol": symbol,
                "resolution": CANDLE_RESOLUTION,
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
        raise DeltaAPIError(f"No {CANDLE_RESOLUTION} candle data returned for {symbol}")

    rows = _rows_from_raw(all_raw)
    expected = expected_1m_candles(days)
    if len(rows) > expected:
        rows = rows[-expected:]
    return rows
