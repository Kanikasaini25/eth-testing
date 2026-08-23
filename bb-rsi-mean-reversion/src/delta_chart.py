"""Delta-style dark candlestick chart for the Streamlit backtest (IST)."""

from __future__ import annotations

from src.backtest import Trade
from src.config import DEFAULT_CONTRACT_ETH
from src.risk import trade_risk_reward
from src.session import IST, parse_bar_time

DELTA_BG = "#131722"
DELTA_PAPER = "#0e1117"
DELTA_UP = "#26a69a"
DELTA_DOWN = "#ef5350"
DELTA_GRID = "#2a2e39"


def slice_around_trade(ohlcv: list[dict], trade: Trade, pad: int = 90) -> list[dict]:
    return slice_around_trades(ohlcv, [trade], pad=pad)


def slice_around_trades(ohlcv: list[dict], trades: list[Trade], pad: int = 90) -> list[dict]:
    if not ohlcv or not trades:
        return ohlcv
    start = min(_nearest_index(ohlcv, trade.entry_ts) for trade in trades)
    end = max(_nearest_index(ohlcv, trade.exit_ts) for trade in trades)
    left = max(0, start - pad)
    right = min(len(ohlcv), end + pad + 1)
    return ohlcv[left:right]


def slice_latest(ohlcv: list[dict], bars: int = 360) -> list[dict]:
    if len(ohlcv) <= bars:
        return ohlcv
    return ohlcv[-bars:]


def _nearest_index(ohlcv: list[dict], timestamp_iso: str) -> int:
    times = [row["timestamp"] for row in ohlcv]
    if timestamp_iso in times:
        return times.index(timestamp_iso)
    target = parse_bar_time(timestamp_iso)
    best = 0
    best_delta = None
    for idx, row in enumerate(ohlcv):
        delta = abs((parse_bar_time(row["timestamp"]) - target).total_seconds())
        if best_delta is None or delta < best_delta:
            best = idx
            best_delta = delta
    return best


def _trades_in_window(ohlcv: list[dict], trades: list[Trade]) -> list[Trade]:
    start = parse_bar_time(ohlcv[0]["timestamp"])
    end = parse_bar_time(ohlcv[-1]["timestamp"])
    visible: list[Trade] = []
    for trade in trades:
        entry = parse_bar_time(trade.entry_ts)
        exit_at = parse_bar_time(trade.exit_ts)
        if entry <= end and exit_at >= start:
            visible.append(trade)
    return visible


def build_delta_figure(
    ohlcv: list[dict],
    trades: list[Trade] | None = None,
    *,
    symbol: str = "ETHUSD",
) -> object:
    """Interactive candlesticks + volume, styled like Delta / TradingView."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    if not ohlcv:
        fig = go.Figure()
        fig.update_layout(title="No candles", template="plotly_dark")
        return fig

    times = [_ist_label(row["timestamp"]) for row in ohlcv]
    opens = [float(row["open"]) for row in ohlcv]
    highs = [float(row["high"]) for row in ohlcv]
    lows = [float(row["low"]) for row in ohlcv]
    closes = [float(row["close"]) for row in ohlcv]
    volumes = [float(row.get("volume") or 0) for row in ohlcv]
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.72, 0.28],
        specs=[[{"secondary_y": False}], [{"secondary_y": False}]],
    )
    _add_price_pane(fig, times, opens, highs, lows, closes)
    _add_volume_pane(fig, times, volumes, closes)
    if trades:
        trades = _trades_in_window(ohlcv, trades)
        _add_trade_markers(fig, ohlcv, trades, times)
        for idx, trade in enumerate(trades, 1):
            _add_rr_tool(fig, ohlcv, times, trade, tag=f"T{idx}")
    fig.update_layout(
        title=f"{symbol} 1m · Delta-style chart (IST)",
        template="plotly_dark",
        paper_bgcolor=DELTA_PAPER,
        plot_bgcolor=DELTA_BG,
        height=760,
        margin=dict(l=56, r=16, t=48, b=24),
        legend=dict(orientation="h", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
        hovermode="x unified",
        xaxis_rangeslider_visible=False,
    )
    fig.update_xaxes(gridcolor=DELTA_GRID, showgrid=True, rangeslider_visible=False)
    fig.update_yaxes(gridcolor=DELTA_GRID, showgrid=True)
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Vol", row=2, col=1)
    return fig


def _ist_label(timestamp_iso: str) -> str:
    return parse_bar_time(timestamp_iso).astimezone(IST).strftime("%Y-%m-%d %H:%M")


def _add_price_pane(fig, times, opens, highs, lows, closes) -> None:
    import plotly.graph_objects as go

    fig.add_trace(
        go.Candlestick(
            x=times,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="OHLC",
            increasing_line_color=DELTA_UP,
            decreasing_line_color=DELTA_DOWN,
            increasing_fillcolor=DELTA_UP,
            decreasing_fillcolor=DELTA_DOWN,
            showlegend=False,
        ),
        row=1,
        col=1,
    )


def _add_volume_pane(fig, times, volumes, closes) -> None:
    import plotly.graph_objects as go

    colors = [DELTA_UP if closes[i] >= closes[i - 1] else DELTA_DOWN for i in range(len(closes))]
    if colors:
        colors[0] = DELTA_UP
    fig.add_trace(
        go.Bar(x=times, y=volumes, name="Volume", marker_color=colors, showlegend=False),
        row=2,
        col=1,
    )


def _add_trade_markers(fig, ohlcv: list[dict], trades: list[Trade], times: list[str]) -> None:
    import plotly.graph_objects as go

    for trade in trades:
        entry_i = _nearest_index(ohlcv, trade.entry_ts)
        exit_i = _nearest_index(ohlcv, trade.exit_ts)
        entry_symbol = "triangle-up" if trade.side == "long" else "triangle-down"
        fig.add_trace(
            go.Scatter(
                x=[times[entry_i]],
                y=[trade.entry_price],
                mode="markers",
                name=f"{trade.side.upper()} in",
                marker=dict(symbol=entry_symbol, size=12, color="#42a5f5"),
                showlegend=False,
                hovertext=f"{trade.side.upper()} entry {trade.entry_price:.2f}",
            ),
            row=1,
            col=1,
        )
        exit_color = DELTA_UP if trade.pnl_usd >= 0 else DELTA_DOWN
        fig.add_trace(
            go.Scatter(
                x=[times[exit_i]],
                y=[trade.exit_price],
                mode="markers",
                name="exit",
                marker=dict(symbol="x", size=10, color=exit_color),
                showlegend=False,
                hovertext=f"exit {trade.exit_price:.2f}  {trade.pnl_usd:+.2f}",
            ),
            row=1,
            col=1,
        )


def _add_rr_tool(fig, ohlcv: list[dict], times: list[str], trade: Trade, tag: str = "") -> None:
    """TradingView-style long/short position tool: stop (red), target (green), R:R."""
    import plotly.graph_objects as go

    entry_i = _nearest_index(ohlcv, trade.entry_ts)
    exit_i = _nearest_index(ohlcv, trade.exit_ts)
    end_i = min(len(times) - 1, max(exit_i, entry_i + 20))
    x0, x1 = times[entry_i], times[end_i]
    rr = trade_risk_reward(
        side=trade.side,
        entry_price=trade.entry_price,
        stop_price=trade.stop_price,
        take_profit_price=trade.take_profit_price,
        lots=trade.lots,
        contract_eth=DEFAULT_CONTRACT_ETH,
        realized_pnl=trade.pnl_usd,
    )
    _rr_box(fig, x0, x1, trade.entry_price, trade.take_profit_price, "rgba(38, 166, 154, 0.28)", DELTA_UP)
    _rr_box(fig, x0, x1, trade.entry_price, trade.stop_price, "rgba(239, 83, 80, 0.28)", DELTA_DOWN)
    fig.add_trace(
        go.Scatter(
            x=[x0, x1, x0, x1],
            y=[trade.stop_price, trade.stop_price, trade.take_profit_price, trade.take_profit_price],
            mode="markers",
            marker=dict(size=1, opacity=0),
            showlegend=False,
            hoverinfo="skip",
        ),
        row=1,
        col=1,
    )
    _rr_labels(fig, x0, x1, trade, rr, tag=tag)
    _rr_side_arrow(fig, x0, trade)


def _rr_box(fig, x0: str, x1: str, y0: float, y1: float, fill: str, line: str) -> None:
    fig.add_shape(
        type="rect",
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
        fillcolor=fill,
        line=dict(color=line, width=1),
        layer="below",
        row=1,
        col=1,
    )


def _rr_labels(fig, x0: str, x1: str, trade: Trade, rr: dict[str, float], tag: str = "") -> None:
    mid_reward = (trade.entry_price + trade.take_profit_price) / 2
    mid_risk = (trade.entry_price + trade.stop_price) / 2
    fig.add_shape(
        type="line",
        x0=x0,
        x1=x1,
        y0=trade.entry_price,
        y1=trade.entry_price,
        line=dict(color="#d1d4dc", width=1, dash="dot"),
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=x1,
        y=mid_reward,
        text=f"Target  +${rr['reward_usd']:.2f}",
        showarrow=False,
        xanchor="right",
        font=dict(color=DELTA_UP, size=12),
        bgcolor="rgba(14,17,23,0.55)",
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=x1,
        y=mid_risk,
        text=f"Stop  −${rr['risk_usd']:.2f}",
        showarrow=False,
        xanchor="right",
        font=dict(color=DELTA_DOWN, size=12),
        bgcolor="rgba(14,17,23,0.55)",
        row=1,
        col=1,
    )
    fig.add_annotation(
        x=x0,
        y=trade.entry_price,
        text=f"{tag}  R:R  1 : {rr['ratio']:.2f}".strip(),
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font=dict(color="#f5d76e", size=13),
        bgcolor="rgba(14,17,23,0.7)",
        row=1,
        col=1,
    )


def _rr_side_arrow(fig, x0: str, trade: Trade) -> None:
    """Direction marker outside the R:R boxes: long = red up, short = green down."""
    import plotly.graph_objects as go

    top = max(trade.entry_price, trade.stop_price, trade.take_profit_price)
    bottom = min(trade.entry_price, trade.stop_price, trade.take_profit_price)
    pad = max((top - bottom) * 0.14, 0.8)
    if trade.side == "long":
        y_pos = top + pad
        symbol = "triangle-up"
        color = DELTA_DOWN
        label = "LONG"
    else:
        y_pos = bottom - pad
        symbol = "triangle-down"
        color = DELTA_UP
        label = "SHORT"
    fig.add_trace(
        go.Scatter(
            x=[x0],
            y=[y_pos],
            mode="markers",
            marker=dict(symbol=symbol, size=18, color=color, line=dict(color=color, width=1)),
            showlegend=False,
            hovertext=label,
        ),
        row=1,
        col=1,
    )
