from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class OrderFlowParams:
    enabled: bool = True
    min_dominance: float = 0.60
    min_ratio: float = 1.5
    sweep_lookback_bars: int = 2
    confirm_bars: int = 2
    entry_bars: int = 1
    entry_window_seconds: int = 30
    require_price_align: bool = True
    require_sweep_reversal: bool = True


@dataclass(frozen=True)
class OrderFlowSnapshot:
    buy_volume: float
    sell_volume: float

    @property
    def total(self) -> float:
        return self.buy_volume + self.sell_volume

    @property
    def delta(self) -> float:
        return self.buy_volume - self.sell_volume

    @property
    def buy_dominance(self) -> float:
        return self.buy_volume / self.total if self.total else 0.0

    @property
    def sell_dominance(self) -> float:
        return self.sell_volume / self.total if self.total else 0.0

    @property
    def buy_sell_ratio(self) -> float:
        if self.sell_volume <= 0:
            return float("inf") if self.buy_volume > 0 else 0.0
        return self.buy_volume / self.sell_volume

    @property
    def sell_buy_ratio(self) -> float:
        if self.buy_volume <= 0:
            return float("inf") if self.sell_volume > 0 else 0.0
        return self.sell_volume / self.buy_volume

    def summary(self) -> str:
        if self.total <= 0:
            return "buy=0 sell=0"
        return (
            f"buy={self.buy_volume:.0f} sell={self.sell_volume:.0f} "
            f"dom={self.buy_dominance * 100:.0f}%/{self.sell_dominance * 100:.0f}% "
            f"ratio={self.buy_sell_ratio:.2f}"
        )


def order_flow_params_from_dict(raw: dict | None) -> OrderFlowParams:
    params = raw or {}
    return OrderFlowParams(
        enabled=bool(params.get("use_order_flow_filter", True)),
        min_dominance=float(params.get("order_flow_min_dominance", 0.60)),
        min_ratio=float(params.get("order_flow_min_ratio", 1.5)),
        sweep_lookback_bars=int(params.get("order_flow_sweep_lookback_bars", 2)),
        confirm_bars=int(params.get("order_flow_confirm_bars", 2)),
        entry_bars=int(params.get("order_flow_entry_bars", 1)),
        entry_window_seconds=int(params.get("order_flow_entry_window_seconds", 30)),
        require_price_align=bool(params.get("order_flow_require_price_align", True)),
        require_sweep_reversal=bool(params.get("order_flow_require_sweep_reversal", True)),
    )


def unix_seconds(value: float | int | str) -> float:
    ts = float(value)
    if ts > 1e14:
        return ts / 1_000_000
    if ts > 1e11:
        return ts / 1_000
    return ts


def bar_unix_range(
    row: dict,
    duration_seconds: int | None = None,
) -> tuple[float, float]:
    parsed = datetime.fromisoformat(row["timestamp"])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    start = parsed.timestamp()
    duration = duration_seconds if duration_seconds is not None else 60
    return start, start + duration


def aggressive_side(trade: dict) -> str:
    side = str(trade.get("side") or "").lower()
    if side in {"buy", "sell"}:
        return side
    buyer_role = str(trade.get("buyer_role") or trade.get("r") or "").lower()
    if buyer_role in {"taker", "t"}:
        return "buy"
    if buyer_role in {"maker", "m"}:
        return "sell"
    seller_role = str(trade.get("seller_role") or "").lower()
    if seller_role in {"taker", "t"}:
        return "sell"
    if seller_role in {"maker", "m"}:
        return "buy"
    return ""


def normalize_public_trade(trade: dict) -> dict | None:
    side = aggressive_side(trade)
    if not side or trade.get("timestamp") is None or trade.get("size") is None:
        return None
    return {
        "timestamp": unix_seconds(trade["timestamp"]),
        "size": float(trade["size"]),
        "side": side,
        "price": float(trade.get("price") or trade.get("p") or 0),
    }


def split_bar_volume(row: dict) -> tuple[float, float]:
    volume = float(row.get("volume") or 0)
    high = float(row["high"])
    low = float(row["low"])
    close = float(row["close"])
    if volume <= 0:
        return 0.0, 0.0
    candle_range = high - low
    if candle_range <= 0:
        half = volume / 2
        return half, half
    buy = volume * (close - low) / candle_range
    sell = volume * (high - close) / candle_range
    return buy, sell


def snapshot_from_bars(rows: list[dict]) -> OrderFlowSnapshot:
    buy = sell = 0.0
    for row in rows:
        bar_buy, bar_sell = split_bar_volume(row)
        buy += bar_buy
        sell += bar_sell
    return OrderFlowSnapshot(buy_volume=buy, sell_volume=sell)


def snapshot_from_trades(
    trades: list[dict],
    start_unix: float,
    end_unix: float,
) -> OrderFlowSnapshot:
    buy = sell = 0.0
    for trade in trades:
        ts = float(trade["timestamp"])
        if ts < start_unix or ts > end_unix:
            continue
        size = float(trade["size"])
        if trade["side"] == "buy":
            buy += size
        elif trade["side"] == "sell":
            sell += size
    return OrderFlowSnapshot(buy_volume=buy, sell_volume=sell)


def snapshot_for_bar_tail(
    row: dict,
    trades: list[dict],
    window_seconds: int,
) -> OrderFlowSnapshot:
    start, end = bar_unix_range(row)
    tail_start = max(start, end - max(window_seconds, 1))
    return snapshot_from_trades(trades, tail_start, end)


def is_side_dominant(side: str, snapshot: OrderFlowSnapshot, params: OrderFlowParams) -> bool:
    if snapshot.total <= 0:
        return False
    if side == "long":
        return (
            snapshot.buy_dominance >= params.min_dominance
            and snapshot.buy_sell_ratio >= params.min_ratio
            and snapshot.delta > 0
        )
    return (
        snapshot.sell_dominance >= params.min_dominance
        and snapshot.sell_buy_ratio >= params.min_ratio
        and snapshot.delta < 0
    )


def price_aligned(side: str, rows: list[dict]) -> bool:
    if not rows:
        return False
    start = float(rows[0]["open"])
    end = float(rows[-1]["close"])
    if side == "long":
        return end > start
    return end < start


def reversal_ok(side: str, pre: OrderFlowSnapshot, post: OrderFlowSnapshot) -> bool:
    if side == "long":
        return post.buy_volume > pre.buy_volume and post.buy_dominance > pre.buy_dominance
    return post.sell_volume > pre.sell_volume and post.sell_dominance > pre.sell_dominance


def evaluate_liquidity_order_flow(
    *,
    side: str,
    bars: list[dict],
    signal_index: int,
    entry_index: int,
    params: OrderFlowParams,
    is_reentry: bool = False,
    entry_snapshot: OrderFlowSnapshot | None = None,
) -> tuple[bool, str]:
    if not params.enabled:
        return True, "order flow disabled"
    if signal_index < 0 or entry_index < signal_index or entry_index >= len(bars):
        return False, "order flow: invalid bar window"

    confirm_start = max(signal_index, entry_index - max(params.confirm_bars, 1) + 1)
    confirm_rows = bars[confirm_start : entry_index + 1]
    confirm = snapshot_from_bars(confirm_rows)
    if not is_side_dominant(side, confirm, params):
        return False, f"SKIP {side.upper()}: confirmation volume weak ({confirm.summary()})"
    if params.require_price_align and not price_aligned(side, confirm_rows):
        return False, f"SKIP {side.upper()}: volume not pushing price"

    resolved_entry = (
        entry_snapshot
        if entry_snapshot is not None and entry_snapshot.total > 0
        else snapshot_from_bars(
            bars[max(0, entry_index - max(params.entry_bars, 1) + 1) : entry_index + 1]
        )
    )
    if not is_side_dominant(side, resolved_entry, params):
        return False, f"SKIP {side.upper()}: entry volume flipped ({resolved_entry.summary()})"

    if params.require_sweep_reversal and not is_reentry:
        pre_start = max(0, signal_index - max(params.sweep_lookback_bars, 1))
        pre = snapshot_from_bars(bars[pre_start:signal_index])
        if pre.total > 0 and not reversal_ok(side, pre, confirm):
            return False, f"SKIP {side.upper()}: no order-flow reversal after sweep"

    return True, f"order flow ok ({confirm.summary()})"
