from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import run_backtest
from src.config import (
    DEFAULT_NOTIONAL_USD,
    STRATEGY_FUNDING,
    SYMBOL_SPECS,
    format_ist,
    get_env,
    lots_for_notional,
    symbol_spec,
)
from src.delta_data import DeltaExchangeClient
from src.funding_strategy import screen_funding_history
from src.strategy import StrategyParams

CANDLE_API_URL = "https://api.india.delta.exchange"


def load_ohlcv(symbol: str, resolution: str, days: int, status) -> list[dict]:
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)

    def on_progress(fetched: float, total: int, res: str) -> None:
        status.info(f"Fetching {res} candles ({fetched:.1f}/{total} days)…")

    return client.fetch_historical_ohlcv(symbol, resolution, days, on_progress=on_progress)


def sidebar_params() -> tuple[str, int, StrategyParams]:
    st.sidebar.header("Backtest settings")
    known = list(SYMBOL_SPECS)
    default_symbol = get_env("DELTA_SYMBOL", "ETHUSD").upper()
    symbol = st.sidebar.selectbox(
        "Futures symbol",
        known,
        index=known.index(default_symbol) if default_symbol in known else 0,
    )
    spec = symbol_spec(symbol)
    days = st.sidebar.slider("Lookback days", min_value=1, max_value=365, value=90, step=1)
    st.sidebar.caption("Any period from 1 to 365 days. Short windows start flat, so they can invent an entry on day 1.")
    notional = st.sidebar.number_input(
        "Notional per book (USD)", min_value=100.0, value=DEFAULT_NOTIONAL_USD, step=50.0
    )
    st.sidebar.caption(
        f"1 lot = {spec.contract_value:g} {spec.spot.split('_')[0]}. "
        "Lots are derived from notional so symbols are comparable."
    )
    wallet = st.sidebar.number_input("Starting wallet (USD)", min_value=100.0, value=10000.0, step=100.0)
    gst = st.sidebar.number_input("GST on fees (%)", min_value=0.0, value=18.0, step=1.0)
    taker_fee = st.sidebar.number_input("Taker fee per side (%)", min_value=0.0, value=0.05, step=0.01)
    maker_fee = st.sidebar.number_input("Maker fee per side (%)", min_value=0.0, value=0.02, step=0.01)
    futures_maker = st.sidebar.checkbox("Futures legs as maker (post-only)", value=True)
    exit_confirm = st.sidebar.number_input("Exit confirm readings", min_value=1, value=2, step=1)
    momentum = st.sidebar.checkbox("Require |rate| rising over last 2 readings", value=False)
    skip_mins = st.sidebar.number_input("Skip minutes before settlement", min_value=0, value=30, step=15)
    threshold = st.sidebar.number_input(
        "Funding |rate| threshold (%)", min_value=0.0, value=0.005, step=0.001, format="%.3f"
    )
    confirm = st.sidebar.number_input("Consecutive periods", min_value=1, value=2, step=1)
    params = StrategyParams(
        strategy=STRATEGY_FUNDING,
        position_lots=1,
        contract_value=spec.contract_value,
        fee_pct_per_side=float(taker_fee),
        fee_maker_pct=float(maker_fee),
        starting_wallet_usd=float(wallet),
        gst_pct=float(gst),
        funding_threshold_pct=float(threshold),
        funding_confirm_periods=int(confirm),
        funding_futures_maker=bool(futures_maker),
        funding_exit_confirm=int(exit_confirm),
        funding_require_momentum=bool(momentum),
        funding_skip_minutes_before_settle=int(skip_mins),
        futures_symbol=spec.futures,
        spot_symbol=spec.spot,
    )
    st.session_state["notional"] = float(notional)
    return spec.futures, int(days), params


def render_metrics(result) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL (USD)", f"{result.net_pnl:,.2f}")
    col2.metric("Win rate", f"{result.win_rate * 100:.1f}%")
    col3.metric("Trades", str(result.trade_count))
    col4.metric("Max drawdown", f"{result.max_drawdown:,.2f}")
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Wins", str(result.wins))
    col6.metric("Losses", str(result.losses))
    col7.metric("Profit factor", f"{result.profit_factor:.2f}")
    col8.metric("Fees incl. GST", f"{result.total_fees:,.2f}")
    if result.funding_collected:
        st.caption(f"Funding collected (shorts receive positive rate): ${result.funding_collected:,.2f}")


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
    ("entry_ts", "entry IST"),
    ("exit_ts", "exit IST"),
    ("entry_price", "entry px"),
    ("exit_price", "exit px"),
    ("lots", "lots"),
    ("funding_pnl", "funding"),
    ("fee_usd", "fees"),
    ("net_usd", "Net P/L"),
    ("reason", "reason"),
)


def _cell(value, *, column: str = "") -> str:
    if column in {"entry_ts", "exit_ts"} and value:
        try:
            return format_ist(str(value))
        except ValueError:
            return str(value)
    if isinstance(value, float):
        text = f"{value:,.2f}" if column in {"fee_usd", "net_usd", "funding_pnl"} else f"{value:.2f}"
        if column == "net_usd":
            color = "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#9ca3af"
            return f"<span style='color:{color};font-weight:600'>{text}</span>"
        return text
    return str(value)


def render_trades(trades: list[dict]) -> None:
    total_net = sum(float(row.get("net_usd") or 0.0) for row in trades)
    headers = "".join(f"<th style='text-align:left;padding:6px'>{label}</th>" for _, label in TRADE_COLUMNS)
    rows = []
    for row in trades:
        cells = "".join(
            f"<td style='padding:6px'>{_cell(row.get(key, ''), column=key)}</td>"
            for key, _ in TRADE_COLUMNS
        )
        rows.append(f"<tr>{cells}</tr>")
    totals = {"side": "TOTAL", "net_usd": total_net}
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
        "Times are Asia/Kolkata (UTC+5:30). Funding still prints at 00/08/16 UTC "
        "(5:30 / 13:30 / 21:30 IST). Lots are sized so each book carries the same "
        "USD notional against its INR spot pair."
    )


def render_rules() -> None:
    with st.expander("Hard-coded rules"):
        st.markdown(
            """
- Last **2** settlements with |rate| **≥ 0.005%**, same sign.
- Enter only if expected funding until a typical flip beats the round-trip fee (2 futures + 2 spot).
- Futures legs are **post-only maker**; spot stays taker.
- Exit after **2 consecutive opposite-sign readings**, not the first flip.
- Skip new entries in the last 30 minutes before 00/08/16 **UTC** (5:30 / 13:30 / 21:30 IST) unless |rate| ≥ 0.02%.
- Positive: buy spot + short the perp. Negative: reverse (sell spot + long the perp).
- Only trade books whose funding stayed **≥ 75% one-sided**; the rest churn into fees.
            """
        )


def run_selected(symbol: str, days: int, params: StrategyParams):
    status = st.empty()
    rows = load_ohlcv(symbol, "1h", days, status)
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    funding = client.fetch_funding_ohlcv(symbol, days=days, resolution="1h")
    notional = float(st.session_state.get("notional", DEFAULT_NOTIONAL_USD))
    params.position_lots = lots_for_notional(symbol, float(rows[-1]["close"]), notional)
    screen = screen_funding_history(funding, symbol=symbol)
    status.info("Simulating cash-and-carry funding trades…")
    result = run_backtest(rows, params, funding_rows=funding)
    status.empty()
    return result, len(rows), screen


def main() -> None:
    st.set_page_config(page_title="Delta funding carry", layout="wide")
    st.title("Funding cash-and-carry")
    st.write(
        "Both-sided funding hedge on India Delta: buy spot + short the perp when funding is "
        "stably positive, reverse when it is stably negative. Each book is sized to the same "
        "USD notional against its INR spot pair. Times are Asia/Kolkata (IST, UTC+5:30)."
    )
    symbol, days, params = sidebar_params()
    render_rules()
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, bar_count, screen = run_selected(symbol, days, params)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["bt_result"] = result
        st.session_state["bt_meta"] = (bar_count, symbol, days, params.position_lots, screen)

    stored = st.session_state.get("bt_result")
    meta = st.session_state.get("bt_meta")
    if stored is None or meta is None:
        return
    bar_count, used_symbol, used_days, used_lots, screen = meta
    st.success(
        f"Last run: funding carry · {used_symbol} · {used_lots} lots · "
        f"{used_days} day(s) · {bar_count} bars"
    )
    if screen.tradable:
        st.info(f"Funding screen: {used_symbol} was {screen.note}.")
    else:
        st.warning(
            f"Funding screen: {used_symbol} was {screen.note}. "
            "Books that flip this often usually lose to fees."
        )
    render_metrics(stored)
    st.subheader("Equity curve")
    render_equity_curve(stored.equity)
    st.subheader("Trades")
    if stored.trades:
        render_trades(stored.trades)
    else:
        st.write("No fills in this window. Try a longer lookback.")


if __name__ == "__main__":
    main()
