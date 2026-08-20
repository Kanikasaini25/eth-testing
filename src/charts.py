from __future__ import annotations

from collections import defaultdict

from src.backtest import BacktestResult, Trade


def _group_trade_entries(trades: list[Trade]) -> list[dict]:
    groups: dict[tuple[str, float], list[Trade]] = defaultdict(list)
    for trade in trades:
        groups[(trade.entry_date, trade.entry_price)].append(trade)

    entries: list[dict] = []
    for (entry_date, entry_price), legs in sorted(groups.items()):
        lot_points = sum(leg.points * leg.lots for leg in legs)
        pnl_usd = sum(leg.pnl_usd for leg in legs)
        entries.append(
            {
                "entry_date": entry_date,
                "entry_price": entry_price,
                "exit_date": max(leg.exit_date for leg in legs),
                "exit_price": legs[-1].exit_price,
                "lot_points": round(lot_points, 2),
                "pnl_usd": round(pnl_usd, 2),
                "legs": len(legs),
                "side": "long" if lot_points >= 0 and any(l.points > 0 for l in legs) else "short",
            }
        )
    return entries


def _svg_line_chart(
    values: list[float],
    *,
    width: int = 900,
    height: int = 240,
    stroke: str = "#1f77b4",
    title: str = "",
    y_suffix: str = "",
) -> str:
    if not values:
        return "<p>No data</p>"

    min_val = min(values)
    max_val = max(values)
    value_range = max(max_val - min_val, 1e-9)
    pad_top, pad_bottom = 24, 28
    plot_height = height - pad_top - pad_bottom

    points: list[str] = []
    for index, value in enumerate(values):
        x = (index / max(len(values) - 1, 1)) * width
        y = pad_top + plot_height - ((value - min_val) / value_range) * plot_height
        points.append(f"{x:.1f},{y:.1f}")

    zero_y = pad_top + plot_height - ((0 - min_val) / value_range) * plot_height
    zero_line = ""
    if min_val < 0 < max_val:
        zero_line = (
            f'<line x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}" '
            f'stroke="#ccc" stroke-width="1" stroke-dasharray="4,4"/>'
        )

    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      {zero_line}
      <polyline fill="none" stroke="{stroke}" stroke-width="2"
        points="{" ".join(points)}" />
      <text x="4" y="14" fill="#666" font-size="12">{title}</text>
      <text x="0" y="{pad_top - 4}" fill="#666" font-size="11">
        {max_val:,.1f}{y_suffix}
      </text>
      <text x="0" y="{height - 6}" fill="#666" font-size="11">
        {min_val:,.1f}{y_suffix}
      </text>
    </svg>
    """


def _svg_bar_chart(
    labels: list[str],
    values: list[float],
    *,
    width: int = 900,
    height: int = 260,
    title: str = "",
) -> str:
    if not values:
        return "<p>No data</p>"

    max_abs = max(abs(value) for value in values) or 1.0
    pad_top, pad_bottom, pad_left, pad_right = 20, 40, 8, 8
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    bar_width = plot_width / max(len(values), 1)
    zero_y = pad_top + plot_height / 2

    bars: list[str] = []
    for index, value in enumerate(values):
        bar_height = (abs(value) / max_abs) * (plot_height / 2 - 4)
        x = pad_left + index * bar_width + bar_width * 0.15
        w = bar_width * 0.7
        color = "#2ca02c" if value >= 0 else "#d62728"
        if value >= 0:
            y = zero_y - bar_height
        else:
            y = zero_y
        bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{bar_height:.1f}" fill="{color}" rx="2"/>')

    label_step = max(1, len(labels) // 12)
    x_labels: list[str] = []
    for index, label in enumerate(labels):
        if index % label_step != 0 and index != len(labels) - 1:
            continue
        x = pad_left + index * bar_width + bar_width * 0.5
        x_labels.append(
            f'<text x="{x:.1f}" y="{height - 8}" fill="#666" font-size="9" '
            f'text-anchor="middle" transform="rotate(-35 {x:.1f} {height - 8})">{label}</text>'
        )

    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}"
        stroke="#999" stroke-width="1"/>
      {"".join(bars)}
      {"".join(x_labels)}
      <text x="4" y="14" fill="#666" font-size="12">{title}</text>
    </svg>
    """


def render_cumulative_pnl_chart(backtest: BacktestResult) -> str:
    entries = _group_trade_entries(backtest.trades)
    cumulative: list[float] = []
    running = 0.0
    for entry in entries:
        running += entry["pnl_usd"]
        cumulative.append(running)
    return _svg_line_chart(
        cumulative,
        stroke="#9467bd",
        title="Cumulative P&L (USD)",
        y_suffix="",
    )


def render_trade_pnl_bars(backtest: BacktestResult) -> str:
    entries = _group_trade_entries(backtest.trades)
    labels = [entry["entry_date"][:10] for entry in entries]
    values = [entry["pnl_usd"] for entry in entries]
    return _svg_bar_chart(
        labels,
        values,
        title="P&L per entry (USD) — green = win, red = loss",
    )


def render_win_loss_summary(backtest: BacktestResult) -> str:
    entries = _group_trade_entries(backtest.trades)
    wins = sum(1 for entry in entries if entry["pnl_usd"] > 0)
    losses = sum(1 for entry in entries if entry["pnl_usd"] < 0)
    breakeven = sum(1 for entry in entries if entry["pnl_usd"] == 0)
    total = max(len(entries), 1)

    segments: list[tuple[int, str, str]] = [
        (wins, "#2ca02c", "Wins"),
        (losses, "#d62728", "Losses"),
    ]
    if breakeven:
        segments.append((breakeven, "#888", "Breakeven"))

    x = 20.0
    parts: list[str] = []
    for count, color, label in segments:
        bar_width = (count / total) * 860
        if bar_width <= 0:
            continue
        parts.append(
            f'<rect x="{x:.1f}" y="36" width="{bar_width:.1f}" height="32" fill="{color}" rx="4"/>'
            f'<text x="{x + bar_width / 2:.1f}" y="56" fill="white" font-size="11" '
            f'text-anchor="middle">{label} {count}</text>'
        )
        x += bar_width

    return f"""
    <svg width="900" height="90" viewBox="0 0 900 90">
      <text x="4" y="16" fill="#666" font-size="12">Entry win/loss summary ({len(entries)} setups)</text>
      {"".join(parts)}
    </svg>
    """


def _day_index(ohlcv: list[dict], date_prefix: str) -> int | None:
    for index, row in enumerate(ohlcv):
        if row["timestamp"][:10] == date_prefix[:10]:
            return index
    return None


def render_trades_on_price(ohlcv: list[dict], backtest: BacktestResult) -> str:
    if not ohlcv or not backtest.trades:
        return "<p>No price or trade data.</p>"

    entries = _group_trade_entries(backtest.trades)
    if not entries:
        return "<p>No trades to plot.</p>"

    trade_days = {entry["entry_date"][:10] for entry in entries}
    indices = sorted(
        index
        for index, row in enumerate(ohlcv)
        if row["timestamp"][:10] in trade_days
    )
    if not indices:
        indices = list(range(max(0, len(ohlcv) - 60), len(ohlcv)))

    start = max(0, indices[0] - 5)
    end = min(len(ohlcv), indices[-1] + 6)
    window = ohlcv[start:end]
    closes = [float(row["close"]) for row in window]

    width, height = 900, 280
    pad_top, pad_bottom = 20, 30
    plot_height = height - pad_top - pad_bottom
    min_price = min(closes)
    max_price = max(closes)
    price_range = max(max_price - min_price, 1e-9)

    def x_for_global_index(global_index: int) -> float:
        local = global_index - start
        return (local / max(len(window) - 1, 1)) * width

    def y_for_price(price: float) -> float:
        return pad_top + plot_height - ((price - min_price) / price_range) * plot_height

    price_points = [
        f"{x_for_global_index(start + index):.1f},{y_for_price(price):.1f}"
        for index, price in enumerate(closes)
    ]

    markers: list[str] = []
    for entry in entries:
        entry_index = _day_index(ohlcv, entry["entry_date"])
        if entry_index is None or entry_index < start or entry_index >= end:
            continue
        x = x_for_global_index(entry_index)
        entry_y = y_for_price(entry["entry_price"])
        exit_y = y_for_price(entry["exit_price"])
        color = "#2ca02c" if entry["lot_points"] >= 0 else "#d62728"
        markers.append(
            f'<circle cx="{x:.1f}" cy="{entry_y:.1f}" r="5" fill="#1f77b4" stroke="white" stroke-width="1"/>'
            f'<circle cx="{x:.1f}" cy="{exit_y:.1f}" r="5" fill="{color}" stroke="white" stroke-width="1"/>'
            f'<line x1="{x:.1f}" y1="{entry_y:.1f}" x2="{x:.1f}" y2="{exit_y:.1f}" '
            f'stroke="{color}" stroke-width="1.5" stroke-dasharray="3,3" opacity="0.7"/>'
        )

    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <polyline fill="none" stroke="#aaa" stroke-width="1.5"
        points="{" ".join(price_points)}" />
      {"".join(markers)}
      <text x="4" y="14" fill="#666" font-size="12">
        Trades on price — blue = entry, green/red = exit
      </text>
      <text x="0" y="{pad_top + 4}" fill="#666" font-size="11">${max_price:,.2f}</text>
      <text x="0" y="{height - 6}" fill="#666" font-size="11">${min_price:,.2f}</text>
      <text x="4" y="{height - 6}" fill="#666" font-size="10">
        {window[0]["timestamp"][:10]} → {window[-1]["timestamp"][:10]}
      </text>
    </svg>
    """
