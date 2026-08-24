"""SVG charts for the BB/RSI Streamlit backtest UI."""

from __future__ import annotations

from src.backtest import BacktestResult, Trade
from src.session import format_ist_clock


def _ist_caption(window: list[dict]) -> str:
    return f"{format_ist_clock(window[0]['timestamp'])} → {format_ist_clock(window[-1]['timestamp'])} IST"


def downsample(rows: list[dict], max_points: int = 900) -> tuple[list[dict], list[int]]:
    if len(rows) <= max_points:
        return rows, list(range(len(rows)))
    step = len(rows) / max_points
    indices = [int(index * step) for index in range(max_points)]
    indices[-1] = len(rows) - 1
    return [rows[index] for index in indices], indices


def _line_chart(
    values: list[float],
    *,
    width: int = 900,
    height: int = 240,
    stroke: str = "#1f77b4",
    title: str = "",
    y_prefix: str = "",
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
    zero = ""
    if min_val < 0 < max_val:
        zero_y = pad_top + plot_height - ((0 - min_val) / value_range) * plot_height
        zero = (
            f'<line x1="0" y1="{zero_y:.1f}" x2="{width}" y2="{zero_y:.1f}" '
            f'stroke="#ccc" stroke-width="1" stroke-dasharray="4,4"/>'
        )
    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      {zero}
      <polyline fill="none" stroke="{stroke}" stroke-width="2" points="{" ".join(points)}" />
      <text x="4" y="14" fill="#666" font-size="12">{title}</text>
      <text x="0" y="{pad_top - 4}" fill="#666" font-size="11">{y_prefix}{max_val:,.1f}</text>
      <text x="0" y="{height - 6}" fill="#666" font-size="11">{y_prefix}{min_val:,.1f}</text>
    </svg>
    """


def _bar_chart(labels: list[str], values: list[float], title: str) -> str:
    if not values:
        return "<p>No trades to chart.</p>"
    max_abs = max(abs(value) for value in values) or 1.0
    pad_top, pad_bottom, pad_left, pad_right = 20, 40, 8, 8
    width, height = 900, 260
    plot_width = width - pad_left - pad_right
    plot_height = height - pad_top - pad_bottom
    bar_width = plot_width / max(len(values), 1)
    zero_y = pad_top + plot_height / 2
    bars: list[str] = []
    for index, value in enumerate(values):
        bar_height = (abs(value) / max_abs) * (plot_height / 2 - 4)
        x = pad_left + index * bar_width + bar_width * 0.15
        y = zero_y - bar_height if value >= 0 else zero_y
        color = "#2ca02c" if value >= 0 else "#d62728"
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.7:.1f}" '
            f'height="{bar_height:.1f}" fill="{color}" rx="2"/>'
        )
    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <line x1="{pad_left}" y1="{zero_y:.1f}" x2="{width - pad_right}" y2="{zero_y:.1f}"
        stroke="#999" stroke-width="1"/>
      {"".join(bars)}
      <text x="4" y="14" fill="#666" font-size="12">{title}</text>
    </svg>
    """


def render_equity_chart(result: BacktestResult) -> str:
    return _line_chart(
        result.equity_curve,
        stroke="#9467bd",
        title="Equity curve (USD wallet + open P/L)",
        y_prefix="$",
    )


def render_cumulative_pnl(result: BacktestResult) -> str:
    running = 0.0
    values: list[float] = []
    for trade in result.trades:
        running += trade.pnl_usd
        values.append(running)
    return _line_chart(values, stroke="#1f77b4", title="Cumulative realized P/L (USD)", y_prefix="$")


def render_trade_pnl_bars(result: BacktestResult) -> str:
    labels = [trade.entry_ts[5:16] for trade in result.trades]
    values = [trade.pnl_usd for trade in result.trades]
    return _bar_chart(labels, values, "P/L per trade (USD) — green = win, red = loss")


def render_win_loss(result: BacktestResult) -> str:
    total = max(len(result.trades), 1)
    segments = [
        (result.wins, "#2ca02c", "Wins"),
        (result.losses, "#d62728", "Losses"),
    ]
    even = len(result.trades) - result.wins - result.losses
    if even:
        segments.append((even, "#888", "Flat"))
    x = 20.0
    parts: list[str] = []
    for count, color, label in segments:
        width = (count / total) * 860
        if width <= 0:
            continue
        parts.append(
            f'<rect x="{x:.1f}" y="36" width="{width:.1f}" height="32" fill="{color}" rx="4"/>'
            f'<text x="{x + width / 2:.1f}" y="56" fill="white" font-size="11" '
            f'text-anchor="middle">{label} {count}</text>'
        )
        x += width
    return f"""
    <svg width="900" height="90" viewBox="0 0 900 90">
      <text x="4" y="16" fill="#666" font-size="12">Win / loss ({len(result.trades)} trades)</text>
      {"".join(parts)}
    </svg>
    """


def render_price_with_bands(ohlcv: list[dict]) -> str:
    window, _indices = downsample(ohlcv)
    plot_close = [float(row["close"]) for row in window]
    if not plot_close:
        return "<p>No price data.</p>"
    return _multi_line(
        [plot_close],
        colors=["#1f77b4"],
        title="Price (5m close)",
        y_prefix="$",
        caption=_ist_caption(window),
    )


def render_rsi_chart(ohlcv: list[dict]) -> str:
    _ = ohlcv
    return "<p>RSI is not used in this strategy.</p>"


def render_trades_on_price(ohlcv: list[dict], trades: list[Trade]) -> str:
    if not ohlcv or not trades:
        return "<p>No trades to plot on price.</p>"
    window, indices = downsample(ohlcv)
    closes = [float(row["close"]) for row in window]
    min_price, max_price = min(closes), max(closes)
    for trade in trades:
        min_price = min(min_price, trade.entry_price, trade.exit_price)
        max_price = max(max_price, trade.entry_price, trade.exit_price)
    width, height, pad_top, pad_bottom = 900, 280, 20, 30
    plot_height = height - pad_top - pad_bottom
    price_range = max(max_price - min_price, 1e-9)

    def x_at(global_index: int) -> float:
        local = min(range(len(indices)), key=lambda item: abs(indices[item] - global_index))
        return (local / max(len(window) - 1, 1)) * width

    def y_at(price: float) -> float:
        return pad_top + plot_height - ((price - min_price) / price_range) * plot_height

    points = [
        f"{(index / max(len(closes) - 1, 1)) * width:.1f},{y_at(price):.1f}"
        for index, price in enumerate(closes)
    ]
    ts_to_index = {row["timestamp"]: idx for idx, row in enumerate(ohlcv)}
    markers: list[str] = []
    for trade in trades:
        entry_i = ts_to_index.get(trade.entry_ts)
        exit_i = ts_to_index.get(trade.exit_ts)
        if entry_i is None or exit_i is None:
            continue
        color = "#2ca02c" if trade.pnl_usd >= 0 else "#d62728"
        x1, x2 = x_at(entry_i), x_at(exit_i)
        y1, y2 = y_at(trade.entry_price), y_at(trade.exit_price)
        markers.append(
            f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="1.2" opacity="0.7"/>'
            f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="4" fill="#1f77b4" stroke="white"/>'
            f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="4" fill="{color}" stroke="white"/>'
        )
    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <polyline fill="none" stroke="#aaa" stroke-width="1.4" points="{" ".join(points)}" />
      {"".join(markers)}
      <text x="4" y="14" fill="#666" font-size="12">
        Trades on price — blue = entry, green/red = exit
      </text>
      <text x="0" y="{pad_top + 4}" fill="#666" font-size="11">${max_price:,.2f}</text>
      <text x="0" y="{height - 6}" fill="#666" font-size="11">${min_price:,.2f}</text>
    </svg>
    """


def _filled(values: list[float | None]) -> list[float]:
    last = 0.0
    out: list[float] = []
    for value in values:
        if value is not None:
            last = value
        out.append(last)
    return out


def _filled_one(value: float | None, default: float) -> float:
    return default if value is None else value


def _multi_line(
    series: list[list[float]],
    *,
    colors: list[str],
    title: str,
    y_prefix: str = "",
    caption: str = "",
    y_min: float | None = None,
    y_max: float | None = None,
    guides: list[tuple[float, str]] | None = None,
) -> str:
    width, height, pad_top, pad_bottom = 900, 240, 24, 28
    plot_height = height - pad_top - pad_bottom
    flat = [item for line in series for item in line]
    min_val = y_min if y_min is not None else min(flat)
    max_val = y_max if y_max is not None else max(flat)
    value_range = max(max_val - min_val, 1e-9)

    def y_at(value: float) -> float:
        return pad_top + plot_height - ((value - min_val) / value_range) * plot_height

    polylines: list[str] = []
    for line, color in zip(series, colors, strict=False):
        points = [
            f"{(index / max(len(line) - 1, 1)) * width:.1f},{y_at(value):.1f}"
            for index, value in enumerate(line)
        ]
        polylines.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="1.6" points="{" ".join(points)}" />'
        )
    guide_svg = ""
    for level, color in guides or []:
        y = y_at(level)
        guide_svg += (
            f'<line x1="0" y1="{y:.1f}" x2="{width}" y2="{y:.1f}" '
            f'stroke="{color}" stroke-width="1" stroke-dasharray="4,4" opacity="0.7"/>'
        )
    return f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      {guide_svg}
      {"".join(polylines)}
      <text x="4" y="14" fill="#666" font-size="12">{title}</text>
      <text x="0" y="{pad_top - 4}" fill="#666" font-size="11">{y_prefix}{max_val:,.1f}</text>
      <text x="0" y="{height - 6}" fill="#666" font-size="11">{y_prefix}{min_val:,.1f} {caption}</text>
    </svg>
    """
