from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestParams, run_liquidity_backtest
from src.config import get_env
from src.delta_data import DeltaExchangeClient

CANDLE_API_URL = "https://api.india.delta.exchange"
WARMUP_DAYS = 2


def load_ohlcv(symbol: str, resolution: str, days: int, status) -> list[dict]:
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)

    def on_progress(fetched: float, total: int, res: str) -> None:
        status.info(
            f"Fetching live {res} candles from Delta India ({fetched:.1f}/{total} days, no cache)…"
        )

    return client.fetch_historical_ohlcv(
        symbol=symbol,
        resolution=resolution,
        days=days,
        on_progress=on_progress,
    )


def sidebar_params() -> tuple[str, int, BacktestParams]:
    st.sidebar.header("Backtest settings")
    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD"))
    days = st.sidebar.select_slider(
        "Lookback days",
        options=[3, 7, 14, 21, 30, 45, 60, 90, 180, 200, 365],
        value=365,
    )
    st.sidebar.caption(
        "365 = 1 year of live 1-minute candles. That download can take several minutes."
    )
    lots = st.sidebar.number_input("Trade size (lots)", min_value=1, value=100, step=1)
    target = st.sidebar.number_input("Take profit (points)", min_value=1.0, value=30.0, step=1.0)
    left = st.sidebar.number_input("Swing left bars", min_value=1, value=2, step=1)
    right = st.sidebar.number_input("Swing right bars", min_value=1, value=2, step=1)
    lookback = st.sidebar.number_input("Swing lookback (15m bars)", min_value=5, value=48, step=1)
    timeout = st.sidebar.number_input("Confirm timeout (minutes)", min_value=5, value=90, step=5)
    sl_buffer = st.sidebar.number_input("Stop buffer (points)", min_value=0.0, value=1.0, step=0.5)
    max_sl = st.sidebar.number_input("Max stop (points)", min_value=0.0, value=15.0, step=1.0)
    min_sweep = st.sidebar.number_input("Min grab through swing (points)", min_value=0.0, value=3.0, step=0.5)
    min_body = st.sidebar.number_input("Min 1m confirm body (points)", min_value=0.0, value=1.5, step=0.5)
    use_sl = st.sidebar.checkbox("Use stop at liquidity-grab extreme", value=True)
    require_reclaim = st.sidebar.checkbox("Require reclaim of the 15m swing", value=True)
    close_back = st.sidebar.checkbox("15m must wick through and close back", value=True)
    close_break = st.sidebar.checkbox("Second 1m must close beyond the first", value=False)
    one_shot = st.sidebar.checkbox("Only the first two 1m candles after the grab", value=False)
    use_partial = st.sidebar.checkbox("Scale out 80% at take profit, run 20%", value=True)
    runner_tp = st.sidebar.number_input(
        "Runner take profit (points, 0 = let 20% run to breakeven/stop)",
        min_value=0.0,
        value=90.0,
        step=10.0,
    )
    wallet = st.sidebar.number_input("Starting wallet (USD)", min_value=100.0, value=10000.0, step=100.0)
    taker_fee = st.sidebar.number_input(
        "Taker fee per side (%)", min_value=0.0, value=0.05, step=0.01, format="%.3f"
    )
    maker_fee = st.sidebar.number_input(
        "Maker fee per side (%)", min_value=0.0, value=0.02, step=0.01, format="%.3f"
    )
    maker_tp = st.sidebar.checkbox("Use maker fee on take-profit limits", value=True)
    maker_entry = st.sidebar.checkbox("Use maker fee on entries (resting limits)", value=False)
    scalper = st.sidebar.checkbox(
        "Delta scalper offer (0 close fee if exit ≤ 30 min)", value=True
    )
    apply_gst = st.sidebar.checkbox("Add 18% GST on fees", value=False)
    st.sidebar.caption(
        "Delta India ETHUSD: taker 0.05%, maker 0.02%. "
        "Join the Scalper Offer on the ETHUSD page first — it waives the closing "
        "fee when a fill (including the 80% scale-out) closes within 30 minutes. "
        "Break entries are taker in live trading; maker-on-entry is optimistic. "
        "India GST is 18% on the fee itself."
    )
    params = BacktestParams(
        target_points=float(target),
        position_lots=int(lots),
        fee_pct_per_side=float(taker_fee),
        fee_maker_pct=float(maker_fee),
        maker_on_take_profit=bool(maker_tp),
        maker_on_entry=bool(maker_entry),
        scalper_offer=bool(scalper),
        gst_pct=18.0 if apply_gst else 0.0,
        starting_wallet_usd=float(wallet),
        swing_left=int(left),
        swing_right=int(right),
        swing_lookback=int(lookback),
        confirm_timeout_minutes=int(timeout),
        sl_buffer_points=float(sl_buffer),
        use_stop_loss=bool(use_sl),
        max_sl_points=float(max_sl),
        min_sweep_points=float(min_sweep),
        require_reclaim=bool(require_reclaim),
        require_close_back=bool(close_back),
        min_confirm_body=float(min_body),
        require_close_break=bool(close_break),
        one_shot_confirm=bool(one_shot),
        partial_exit_pct=80.0 if use_partial else 0.0,
        runner_target_points=float(runner_tp),
    )
    return symbol.strip().upper(), int(days), params


def render_metrics(result) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL (USD)", f"{result.net_pnl:,.2f}")
    col2.metric("Net points", f"{result.net_points:,.2f}")
    col3.metric("Win rate", f"{result.win_rate * 100:.1f}%")
    col4.metric("Trades", str(result.trade_count))
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Take profits", str(result.tp_count))
    col6.metric("Stop losses", str(result.sl_count))
    col7.metric("Profit factor", f"{result.profit_factor:.2f}")
    col8.metric("Max drawdown", f"{result.max_drawdown:,.2f}")
    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Total fees", f"{result.total_fees:,.2f}")
    col10.metric("Avg win (pts)", f"{result.avg_win_points:,.2f}")
    col11.metric("Avg loss (pts)", f"{result.avg_loss_points:,.2f}")
    col12.metric("Liquidity grabs", str(result.grab_count))
    scalped = sum(1 for trade in result.trades if trade.get("scalper_applied"))
    if scalped:
        st.caption(
            f"Scalper offer waived the close fee on {scalped} of {result.trade_count} fills "
            "(exit within 30 minutes)."
        )


def render_equity_curve(equity: list[dict]) -> None:
    values = [float(point["wallet"]) for point in equity]
    if len(values) < 2:
        st.info("No trades in this window.")
        return
    width, height, pad = 900, 240, 16
    low, high = min(values), max(values)
    span = max(high - low, 1.0)
    points: list[str] = []
    for index, value in enumerate(values):
        x = pad + (index / (len(values) - 1)) * (width - 2 * pad)
        y = height - pad - ((value - low) / span) * (height - 2 * pad)
        points.append(f"{x:.1f},{y:.1f}")
    color = "#16a34a" if values[-1] >= values[0] else "#dc2626"
    st.html(
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="240" '
        f'style="background:#0e1117;border-radius:8px;">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
        f'points="{" ".join(points)}" />'
        f'<text x="{pad}" y="18" fill="#9ca3af" font-size="12">{high:,.2f}</text>'
        f'<text x="{pad}" y="{height - 6}" fill="#9ca3af" font-size="12">{low:,.2f}</text>'
        f"</svg>"
    )


TRADE_COLUMNS = (
    ("side", "side"),
    ("grab_ts", "liq grab"),
    ("entry_ts", "entry"),
    ("exit_ts", "exit"),
    ("entry_price", "entry px"),
    ("exit_price", "exit px"),
    ("stop_loss", "stop"),
    ("target", "target"),
    ("swing_price", "swing"),
    ("lots", "lots"),
    ("points", "points"),
    ("fee_usd", "fees"),
    ("net_usd", "Net P/L"),
    ("reason", "reason"),
)


def _cell(value, *, column: str = "") -> str:
    if isinstance(value, float):
        text = f"{value:,.2f}" if column in {"fee_usd", "net_usd"} else f"{value:.2f}"
        if column == "net_usd":
            color = "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#9ca3af"
            return f"<span style='color:{color};font-weight:600'>{text}</span>"
        return text
    return str(value)


def render_trades(trades: list[dict]) -> None:
    total_points = sum(float(row["points"]) for row in trades)
    total_fees = sum(float(row.get("fee_usd") or 0.0) for row in trades)
    total_net = sum(float(row.get("net_usd") or 0.0) for row in trades)
    headers = "".join(f"<th style='text-align:left;padding:6px'>{label}</th>" for _, label in TRADE_COLUMNS)
    rows = []
    for row in trades:
        cells = "".join(
            f"<td style='padding:6px'>{_cell(row.get(key, ''), column=key)}</td>"
            for key, _ in TRADE_COLUMNS
        )
        rows.append(f"<tr>{cells}</tr>")
    totals = {"side": "TOTAL", "points": total_points, "fee_usd": total_fees, "net_usd": total_net}
    total_cells = "".join(
        f"<td style='padding:6px'><b>{_cell(totals.get(key, ''), column=key)}</b></td>"
        for key, _ in TRADE_COLUMNS
    )
    st.html(
        "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr style='border-top:2px solid #9ca3af'>{total_cells}</tr></tfoot></table></div>"
    )
    st.caption(
        f"Fees: {total_fees:,.2f} USD · Net P/L: {total_net:+,.2f} USD. "
        "Delta ETHUSD: 1 lot = 0.01 ETH ($0.01 per point). "
        "80 lots at +30 pts ≈ $24; the 20-lot runner targets +90 pts."
    )


def render_rules() -> None:
    with st.expander("Strategy rules"):
        st.markdown(
            """
- Mark 15-minute swing highs and lows (fractal, 2 bars left/right).
- **Downside grab:** a 15-minute candle wicks at least 3 points below a swing low and closes back above it.
- **Upside grab:** a 15-minute candle wicks at least 3 points above a swing high and closes back below it.
- **Entry:** two consecutive 1-minute reversal candles; enter when the second breaks the first. Size 100 lots.
- **Exit:** take **80 lots** off at +30 points. Move the remaining **20 lots** to breakeven and let them run to +90 (or back to entry).
- Skip if the stop would be wider than 15 points. Tiny 1-minute candles do not count.
            """
        )


def run_backtest(symbol: str, days: int, params: BacktestParams):
    status = st.empty()
    fetch_days = int(days + WARMUP_DAYS)
    m15_rows = load_ohlcv(symbol, "15m", fetch_days, status)
    m1_rows = load_ohlcv(symbol, "1m", fetch_days, status)
    status.info("Simulating 15-minute liquidity grabs with 1-minute confirmation…")
    result = run_liquidity_backtest(m15_rows, m1_rows, params)
    status.empty()
    return result, m15_rows, m1_rows


def main() -> None:
    st.set_page_config(page_title="15m Liquidity Grab + 1m Confirmation", layout="wide")
    st.title("15-Minute Liquidity Grab + 1-Minute Confirmation")
    st.write(
        "Fresh India Delta ETHUSD futures candles (no cache). "
        "A 15-minute candle must wick through a swing by at least 3 points and close back; "
        "then two 1-minute reversal candles confirm. Scale out 80% at +30 points and let "
        "20% run to +90 with the stop at breakeven."
    )
    symbol, days, params = sidebar_params()
    render_rules()
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, m15_rows, m1_rows = run_backtest(symbol, days, params)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["liq_result"] = result
        st.session_state["liq_meta"] = (len(m15_rows), len(m1_rows), symbol, days)

    stored = st.session_state.get("liq_result")
    meta = st.session_state.get("liq_meta")
    if stored is None or meta is None:
        return
    m15_count, m1_count, used_symbol, used_days = meta
    st.success(
        f"Last run: {used_symbol} on live India Delta · {used_days} day(s) · "
        f"{m15_count} 15m candles · {m1_count} 1m candles · {stored.swing_count} swings"
    )
    render_metrics(stored)
    st.subheader("Equity curve")
    render_equity_curve(stored.equity)
    st.subheader("Trades")
    if stored.trades:
        render_trades(stored.trades)
    else:
        st.write("No two-candle confirmation fills in this window. Try a longer lookback.")


if __name__ == "__main__":
    main()
