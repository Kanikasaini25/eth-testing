#!/usr/bin/env python3
"""Streamlit backtester for the isolated ETH SMA Bollinger + RSI strategy."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestConfig, BacktestResult, run_backtest
from src.charts import (
    render_cumulative_pnl,
    render_equity_chart,
    render_price_with_bands,
    render_rsi_chart,
    render_trade_pnl_bars,
    render_trades_on_price,
    render_win_loss,
)
from src.delta_chart import build_delta_figure, slice_around_trade, slice_around_trades, slice_latest
from src.config import (
    DAILY_MAX_LOSS_USD,
    DAILY_TRADE_CAP,
    DEFAULT_CONTRACT_ETH,
    MAX_PROFIT_USD,
    PER_TRADE_STOP_USD,
    PROFIT_LOCK_USD,
    TAKE_PROFIT_USD,
    TAKER_FEE_PCT,
    TESTNET_REST_URL,
)
from src.market_data import expected_1m_candles, fetch_historical_1m
from src.risk import trade_risk_reward
from src.session import format_ist_clock
from src.tables import daily_rows, format_usd, trade_rows

st.set_page_config(page_title="BB + RSI Backtest", page_icon="📉", layout="wide")

EXCHANGES = {
    "India Live (recommended for history)": "https://api.india.delta.exchange",
    "India Demo (Testnet)": TESTNET_REST_URL,
    "Global": "https://api.delta.exchange",
}


def main() -> None:
    st.title("ETH BB + RSI Mean Reversion Backtest")
    st.caption(
        "1m SMA Bollinger (20, 2.0) + Cutler RSI(14). Entries at London/US open only. "
        "Isolated from the LQDTY live bot."
    )
    settings = _sidebar()
    if settings["run"]:
        _run(settings)
    result = st.session_state.get("bb_rsi_backtest")
    candles = st.session_state.get("bb_rsi_candles")
    if result is None:
        st.info("Set the window in the sidebar and click **Run backtest**.")
        _rules_help()
        return
    _render_result(result, candles)


def _sidebar() -> dict:
    st.sidebar.header("Backtest")
    exchange = st.sidebar.selectbox("Delta candles", list(EXCHANGES), index=0)
    base_url = EXCHANGES[exchange]
    default_symbol = "ETHUSDT" if exchange == "Global" else "ETHUSD"
    symbol = st.sidebar.text_input("Symbol", value=default_symbol).strip().upper()
    days = st.sidebar.slider("Days of 1m history", min_value=1, max_value=30, value=7)
    st.sidebar.caption(f"{days} days ≈ **{expected_1m_candles(days):,}** 1m candles")
    wallet = st.sidebar.number_input("Starting wallet (USD)", min_value=100.0, value=10_000.0, step=100.0)
    use_cache = st.sidebar.checkbox("Use cached candles", value=True)
    with st.sidebar.expander("Risk (strategy defaults)"):
        cap = st.number_input("Daily trade cap", min_value=1, max_value=20, value=DAILY_TRADE_CAP)
        stop_usd = st.number_input("Per-trade stop ($)", min_value=0.5, value=float(PER_TRADE_STOP_USD), step=0.5)
        tp_usd = st.number_input("Take profit ($)", min_value=5.0, max_value=20.0, value=float(TAKE_PROFIT_USD), step=0.5)
        lock_usd = st.number_input("Profit lock ($)", min_value=1.0, value=float(PROFIT_LOCK_USD), step=0.5)
        kill = st.number_input("Daily kill-switch ($)", min_value=1.0, value=float(DAILY_MAX_LOSS_USD), step=0.5)
        max_usd = st.number_input("Max profit ($)", min_value=5.0, value=float(MAX_PROFIT_USD), step=0.5)
        lock = st.checkbox(
            "Lock profit once reached",
            value=False,
            help="Off by default. +$5 lock after fees cannot cover a -$3.50 stop. Leave off to wait for TP.",
        )
        trail = st.checkbox("Trail toward +$20 (instead of $10 TP)", value=False)
        net_fees = st.checkbox(
            "TP / lock / max are net of fees",
            value=True,
            help="Adds the estimated round-trip taker fee to TP, lock, and max so +$10 is take-home, not gross.",
        )
        fee_pct = st.number_input(
            "Delta fee per side (%)",
            min_value=0.0,
            max_value=1.0,
            value=float(TAKER_FEE_PCT),
            step=0.01,
            help="Charged on entry notional and exit notional. India taker is typically 0.05%.",
        )
    run = st.sidebar.button("Run backtest", type="primary", use_container_width=True)
    return {
        "run": run,
        "base_url": base_url,
        "symbol": symbol,
        "days": days,
        "wallet": wallet,
        "use_cache": use_cache,
        "config": BacktestConfig(
            starting_wallet=wallet,
            daily_trade_cap=int(cap),
            daily_max_loss_usd=float(kill),
            per_trade_stop_usd=float(stop_usd),
            take_profit_usd=float(tp_usd),
            profit_lock_usd=float(lock_usd),
            max_profit_usd=float(max_usd),
            enable_trailing_lock=lock,
            trail_to_max_profit=trail,
            fee_pct_per_side=float(fee_pct),
            net_of_fees=net_fees,
        ),
    }


def _run(settings: dict) -> None:
    status = st.empty()
    try:
        with st.spinner("Downloading 1m candles from Delta..."):
            candles = fetch_historical_1m(
                symbol=settings["symbol"],
                days=settings["days"],
                base_url=settings["base_url"],
                use_cache=settings["use_cache"],
                progress=status.write,
            )
        status.write(f"Running backtest on {len(candles):,} candles...")
        result = run_backtest(
            candles,
            symbol=settings["symbol"],
            days=settings["days"],
            config=settings["config"],
        )
        st.session_state["bb_rsi_backtest"] = result
        st.session_state["bb_rsi_candles"] = candles
        status.empty()
        st.success(f"Backtest complete — {len(result.trades)} trades")
    except Exception as exc:  # noqa: BLE001
        status.empty()
        st.error(f"Backtest failed: {exc}")


def _render_result(result: BacktestResult, candles: list[dict] | None) -> None:
    overview, charts, trades, daily = st.tabs(["Overview", "Charts", "Trades", "Daily"])
    with overview:
        _overview(result, candles or [])
    with charts:
        _charts(result, candles or [])
    with trades:
        _trades(result)
    with daily:
        _daily(result)


def _overview(result: BacktestResult, candles: list[dict]) -> None:
    cols = st.columns(4)
    cols[0].metric("Net P/L", format_usd(result.total_pnl))
    cols[1].metric("Gross P/L", format_usd(result.gross_pnl))
    cols[2].metric("Entry + exit fees", f"${result.total_fees:,.2f}")
    cols[3].metric("Final wallet", format_usd(result.final_wallet))
    cols2 = st.columns(4)
    cols2[0].metric("Trades", len(result.trades))
    cols2[1].metric("Win rate", f"{result.win_rate:.1f}%")
    cols2[2].metric("Max drawdown", format_usd(-result.max_drawdown))
    cols2[3].metric("Buy & hold (1 ETH)", format_usd(result.buy_hold_usd))
    st.caption(
        f"{result.symbol} 1m · {result.candle_count:,} candles · "
        f"{format_ist_clock(result.start_ts)} → {format_ist_clock(result.end_ts)} IST · "
        f"start {format_usd(result.starting_wallet)}"
    )
    st.markdown(render_win_loss(result), unsafe_allow_html=True)
    if candles:
        st.markdown(render_price_with_bands(candles), unsafe_allow_html=True)


def _charts(result: BacktestResult, candles: list[dict]) -> None:
    if candles:
        _delta_chart(result, candles)
    if not result.trades:
        st.warning("No trades generated in this window.")
        return
    st.markdown(render_equity_chart(result), unsafe_allow_html=True)
    st.markdown(render_cumulative_pnl(result), unsafe_allow_html=True)
    st.markdown(render_trade_pnl_bars(result), unsafe_allow_html=True)
    if candles:
        st.markdown(render_trades_on_price(candles, result.trades), unsafe_allow_html=True)
        st.markdown(render_rsi_chart(candles), unsafe_allow_html=True)
    st.caption("Blue = entry, green = winning exit, red = losing exit. RSI uses SMA Cutler, not EMA.")


def _delta_chart(result: BacktestResult, candles: list[dict]) -> None:
    st.subheader("Delta-style chart (IST)")
    st.caption(
        "Same 1m candles as the backtest. Each trade gets its own R:R tool: "
        "green target box, red stop box, labeled T1…Tn."
    )
    window, visible = _chart_window(result, candles)
    fig = build_delta_figure(window, visible, symbol=result.symbol)
    st.plotly_chart(fig, use_container_width=True)
    if visible:
        _rr_table(visible)


def _rr_table(trades: list) -> None:
    rows = []
    for idx, trade in enumerate(trades, 1):
        rr = trade_risk_reward(
            side=trade.side,
            entry_price=trade.entry_price,
            stop_price=trade.stop_price,
            take_profit_price=trade.take_profit_price,
            lots=trade.lots,
            contract_eth=DEFAULT_CONTRACT_ETH,
            realized_pnl=trade.pnl_usd,
        )
        rows.append(
            {
                "#": f"T{idx}",
                "Side": trade.side.upper(),
                "Entry IST": format_ist_clock(trade.entry_ts),
                "R:R": f"1 : {rr['ratio']:.2f}",
                "Risk": f"${rr['risk_usd']:.2f}",
                "Reward": f"${rr['reward_usd']:.2f}",
                "Realized": f"{rr['realized_r']:+.2f}R",
                "Exit": trade.exit_reason,
            }
        )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _chart_window(result: BacktestResult, candles: list[dict]) -> tuple[list[dict], list]:
    options = ["All trades", "Around selected trade", "Last 6 hours", "Full history"]
    if not result.trades:
        options = ["Last 6 hours", "Full history"]
    view = st.radio("Chart window", options, horizontal=True)
    if view == "Last 6 hours":
        return slice_latest(candles, 360), result.trades
    if view == "Full history":
        if len(candles) > 8_000:
            st.caption("Full 1m history can be slow. Zoom after it loads, or pick All trades.")
        return candles, result.trades
    if view == "All trades":
        return slice_around_trades(candles, result.trades, pad=60), result.trades
    labels = [
        f"{idx + 1}. {trade.side.upper()} {format_ist_clock(trade.entry_ts)}  {trade.pnl_usd:+.2f}"
        for idx, trade in enumerate(result.trades)
    ]
    pick = st.selectbox("Focus trade", labels)
    trade = result.trades[labels.index(pick)]
    return slice_around_trade(candles, trade, pad=90), [trade]


def _trades(result: BacktestResult) -> None:
    st.subheader("Trade log")
    if not result.trades:
        st.write("No trades generated.")
        return
    st.dataframe(trade_rows(result), use_container_width=True, hide_index=True)
    st.caption(
        "All times are IST. Entry $ is the 1m close. Match Entry time + Entry OHLC with the Delta India chart."
    )
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("GRAND TOTAL net P/L", format_usd(result.total_pnl))
    col2.metric("Gross P/L", format_usd(result.gross_pnl))
    col3.metric("Total fees", f"${result.total_fees:,.2f}")
    col4.metric("Winning trades", result.wins)
    col5.metric("Losing trades", result.losses)
    st.download_button(
        "Download trades JSON",
        data=json.dumps([asdict(trade) for trade in result.trades], indent=2),
        file_name=f"{result.symbol}_bb_rsi_trades.json",
        mime="application/json",
    )


def _daily(result: BacktestResult) -> None:
    st.subheader("IST daily totals")
    rows = daily_rows(result)
    if not rows:
        st.write("No trades.")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("Last row is the **GRAND TOTAL** across the whole backtest window.")


def _rules_help() -> None:
    st.markdown(
        """
        ### Rules used
        - Long: 1m close/pierce of the **lower SMA Bollinger** and RSI < 30
        - Short: 1m close/pierce of the **upper SMA Bollinger** and RSI > 70
        - Entries only at **market open (IST)**: London **12:30–2:00 PM**, US **7:00–9:30 PM**
        - Fade the **previous 1h run**: long only after a down hour, short only after an up hour
        - After a **losing trade**, wait **15 minutes from that entry**, then re-enter on **1h trend only** (max **2 SL per open**)
        - After a **profit**, no more entries until the **next open** (London → US, or US → next London)
        - No entries in the London grind, 5:30–7:00 PM, or overnight after 9:30 PM
        - Max **4 trades / IST day**. Kill-switch at **-$14** daily P/L
        - **100 lots** every trade. Stop **-$3.50** (price). Base TP **+$10 net of fees**
        - **+$5 lock is off** — after fees a +$5 winner cannot pay for a stop
        - Delta **taker fee 0.05%** of notional on entry and again on exit
        """
    )


if __name__ == "__main__":
    main()
