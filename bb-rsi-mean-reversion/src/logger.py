"""Structured IST logs: timestamp, signal, prices, daily PnL, trades taken."""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.config import LOG_DIR

IST = timezone(timedelta(hours=5, minutes=30))


class IstFormatter(logging.Formatter):
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        stamp = datetime.fromtimestamp(record.created, tz=timezone.utc).astimezone(IST)
        return stamp.strftime("%Y-%m-%d %H:%M:%S IST")


def setup_logger(name: str = "bb-rsi") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = IstFormatter("%(asctime)s | %(levelname)s | %(message)s")

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    logger.addHandler(stream)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(Path(LOG_DIR) / "bb_rsi.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.propagate = False
    return logger


def scan_line(
    *,
    close: float,
    mark: float,
    session: str,
    signal: str,
    daily_pnl: float,
    trades_today: int,
    trade_cap: int,
    reason: str = "",
) -> str:
    extra = f" reason={reason}" if reason else ""
    return (
        f"scan close={close:.2f} mark={mark:.2f} session={session} "
        f"signal={signal}{extra} daily_pnl={daily_pnl:+.2f} "
        f"trades_today={trades_today}/{trade_cap}"
    )


def trade_line(
    *,
    signal: str,
    entry: float,
    sl: float,
    tp: float,
    daily_pnl: float,
    trades_today: int,
    trade_cap: int,
    extra: str = "",
) -> str:
    base = (
        f"signal={signal} entry={entry:.2f} sl={sl:.2f} tp={tp:.2f} "
        f"daily_pnl={daily_pnl:+.2f} trades_today={trades_today}/{trade_cap}"
    )
    return f"{base} {extra}".strip()
