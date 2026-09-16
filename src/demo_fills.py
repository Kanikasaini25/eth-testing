from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.delta_trading import DeltaTradingClient


def fill_epoch(fill: dict[str, Any]) -> float:
    for key in ("created_at", "updated_at", "time", "timestamp"):
        raw = fill.get(key)
        if raw is None:
            continue
        if isinstance(raw, (int, float)):
            return float(raw)
        text = str(raw).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            continue
    return 0.0


def _fill_iso(fill: dict[str, Any]) -> str:
    ts = fill_epoch(fill)
    if ts:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    return str(fill.get("created_at") or "")


def _parse_fills_payload(raw: Any) -> tuple[list[dict[str, Any]], str | None]:
    if isinstance(raw, dict):
        if raw.get("success") is False:
            err = raw.get("error") or raw
            raise RuntimeError(f"Delta fills API error: {err}")
        batch = list(raw.get("result") or [])
        meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
        after = meta.get("after")
        return batch, str(after) if after is not None else None
    if isinstance(raw, list):
        return list(raw), None
    return [], None


def fetch_fills_in_window(
    broker: DeltaTradingClient,
    *,
    start_epoch: int,
    end_epoch: int,
    page_size: int = 100,
    max_pages: int = 20,
) -> list[dict[str, Any]]:
    """Pull authenticated fills for the configured order account (e.g. testnet demo)."""
    if not broker.is_configured:
        raise RuntimeError("Set DELTA_API_KEY and DELTA_API_SECRET in .env for demo fills.")

    product_id = broker.get_product_id()
    collected: list[dict[str, Any]] = []
    after: str | None = None

    for _ in range(max_pages):
        query: dict[str, Any] = {"product_id": product_id}
        raw = broker.client.fills(query=query, page_size=page_size, after=after)
        batch, next_after = _parse_fills_payload(raw)
        if not batch:
            break

        for fill in batch:
            ts = fill_epoch(fill)
            if start_epoch <= ts <= end_epoch:
                collected.append(fill)

        if not next_after or next_after == after:
            break
        after = next_after

    return sorted(collected, key=fill_epoch)


@dataclass
class DemoFillResult:
    fills: list[dict[str, Any]] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    net_pnl: float = 0.0
    total_fees: float = 0.0
    source_url: str = ""


def _fee_usd(fill: dict[str, Any], gross_usd: float, fee_pct_per_side: float) -> float:
    for key in ("commission", "fee", "fees"):
        raw = fill.get(key)
        if raw not in (None, ""):
            return abs(float(raw))
    return abs(gross_usd) * (fee_pct_per_side / 100.0)


def fills_to_trade_rows(
    fills: list[dict[str, Any]],
    *,
    usd_per_point_per_lot: float,
    fee_pct_per_side: float,
) -> tuple[list[dict], float, float]:
    """Turn chronological fills into entry/exit rows with USD P&L."""
    trades: list[dict] = []
    pos = 0
    avg_entry = 0.0
    entry_ts = ""
    entry_side = ""
    original_lots = 0
    total_fees = 0.0
    net_pnl = 0.0

    def record_close(
        fill: dict[str, Any],
        close_size: int,
        exit_price: float,
        reason: str,
    ) -> None:
        nonlocal pos, avg_entry, entry_ts, entry_side, original_lots, total_fees, net_pnl
        if close_size <= 0 or not entry_side:
            return
        if entry_side == "long":
            points = exit_price - avg_entry
        else:
            points = avg_entry - exit_price
        gross = points * close_size * usd_per_point_per_lot
        fee = _fee_usd(fill, gross, fee_pct_per_side)
        total_fees += fee
        net = gross - fee
        net_pnl += net
        trades.append(
            {
                "side": entry_side,
                "grab_ts": entry_ts,
                "entry_ts": entry_ts,
                "exit_ts": _fill_iso(fill),
                "entry_price": avg_entry,
                "exit_price": exit_price,
                "stop_loss": 0.0,
                "target": 0.0,
                "swing_price": 0.0,
                "lots": close_size,
                "points": round(points, 4),
                "gross_usd": round(gross, 4),
                "fee_usd": round(fee, 4),
                "net_usd": round(net, 4),
                "reason": reason,
                "wallet": 0.0,
            }
        )
        if entry_side == "long":
            pos -= close_size
        else:
            pos += close_size
        if pos == 0:
            avg_entry = 0.0
            entry_ts = ""
            entry_side = ""
            original_lots = 0

    for fill in fills:
        side = str(fill.get("side") or "").lower()
        size = int(float(fill.get("size") or 0))
        price = float(fill.get("price") or fill.get("fill_price") or 0)
        if size <= 0 or price <= 0 or side not in {"buy", "sell"}:
            continue

        if side == "buy":
            if pos < 0:
                close_size = min(size, abs(pos))
                record_close(fill, close_size, price, "demo_close")
                size -= close_size
            if size > 0:
                if pos == 0:
                    entry_ts = _fill_iso(fill)
                    entry_side = "long"
                    original_lots = size
                    avg_entry = price
                else:
                    avg_entry = ((avg_entry * pos) + (price * size)) / (pos + size)
                    original_lots = max(original_lots, pos + size)
                pos += size
        else:
            if pos > 0:
                close_size = min(size, pos)
                remaining = pos - close_size
                if close_size == original_lots or (original_lots and close_size >= original_lots * 0.4):
                    reason = "take_profit_T1" if remaining > 0 else "runner_take_profit"
                elif remaining == 0:
                    reason = "demo_close"
                else:
                    reason = "demo_partial"
                record_close(fill, close_size, price, reason)
                size -= close_size
            if size > 0:
                if pos == 0:
                    entry_ts = _fill_iso(fill)
                    entry_side = "short"
                    original_lots = size
                    avg_entry = price
                else:
                    avg_entry = ((avg_entry * abs(pos)) + (price * size)) / (abs(pos) + size)
                    original_lots = max(original_lots, abs(pos) + size)
                pos -= size

    return trades, round(net_pnl, 2), round(total_fees, 2)


def load_demo_fills(
    symbol: str,
    *,
    start_epoch: int,
    end_epoch: int,
    usd_per_point_per_lot: float,
    fee_pct_per_side: float,
) -> DemoFillResult:
    broker = DeltaTradingClient(symbol=symbol)
    fills = fetch_fills_in_window(broker, start_epoch=start_epoch, end_epoch=end_epoch)
    trades, net_pnl, total_fees = fills_to_trade_rows(
        fills,
        usd_per_point_per_lot=usd_per_point_per_lot,
        fee_pct_per_side=fee_pct_per_side,
    )
    return DemoFillResult(
        fills=fills,
        trades=trades,
        net_pnl=net_pnl,
        total_fees=total_fees,
        source_url=broker.base_url,
    )
