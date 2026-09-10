"""Streamlit backtest panel for the ETH India volume-bias strategy."""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

from src.backtest import BacktestResult, run_india_live_backtest
from src.config import get_env
from src.timezone import format_india_timestamp


def _format_usd(amount: float) -> str:
    return f"${amount:+,.2f}"


def trade_table_rows(result: BacktestResult) -> list[dict]:
    rows: list[dict] = []
    for index, trade in enumerate(result.trades, start=1):
        rows.append(
            {
                "Trade": index,
                "India day": trade.india_day,
                "Side": "BUY" if trade.side == "long" else "SELL",
                "Day power": trade.bias_label,
                "Buy vol": round(trade.buy_volume, 4),
                "Sell vol": round(trade.sell_volume, 4),
                "Entry": format_india_timestamp(trade.entry_ts),
                "Exit": format_india_timestamp(trade.exit_ts),
                "Entry $": trade.entry_price,
                "Exit $": trade.exit_price,
                "SL (wick)": trade.stop_loss,
                "Target": trade.target,
                "Lots": trade.lots,
                "Points": trade.points,
                "P/L ($)": trade.pnl_usd,
                "Wallet": trade.wallet_balance,
                "Exit reason": trade.exit_reason.replace("_", " "),
            }
        )
    return rows


def render_backtest_tab(symbol: str) -> None:
    st.subheader("India-live backtest")
    st.caption(
        "Fetches **India live** ETH **15m** (pullback) and **1m** (confirmation/entry) candles, "
        "then replays volume-bias → 7:00 PM IST 15m pullback → 1m confirmation → +5% close. "
        "Trail: +1% keep wick SL, +2%→+1%, +3%→+2%, +4%→+3%. "
        "A stop or +5% close can take another pullback the same day. "
        "After **2 wins** or **2 losses**, no more trades that day."
    )

    default_days = min(90, int(get_env("BACKTEST_DAYS", "30") or "30"))
    col1, col2, col3 = st.columns(3)
    with col1:
        start_day = st.date_input(
            "Start date (IST)",
            value=date.today() - timedelta(days=default_days - 1),
            max_value=date.today(),
        )
    with col2:
        end_day = st.date_input("End date (IST)", value=date.today(), max_value=date.today())
    with col3:
        starting_wallet = st.number_input(
            "Starting wallet (USD)",
            min_value=100.0,
            max_value=10_000_000.0,
            value=float(get_env("STARTING_WALLET_USD", "10000") or "10000"),
            step=100.0,
        )

    run = st.button("Run backtest", type="primary", key="run_volume_backtest")
    if run:
        try:
            with st.spinner("Fetching India-live candles and simulating trades..."):
                result = run_india_live_backtest(
                    symbol=symbol,
                    start_day=start_day,
                    end_day=end_day,
                    starting_wallet=starting_wallet,
                )
            st.session_state["backtest_result"] = result
        except Exception as exc:  # noqa: BLE001
            st.error(f"Backtest failed: {exc}")
            return

    result = st.session_state.get("backtest_result")
    if result is None:
        st.info("Choose an IST date range and click **Run backtest**.")
        return

    st.success(
        f"Data: `{result.data_url}` · {result.resolution} · "
        f"{result.candle_count:,} candles · {result.start_day} → {result.end_day} IST"
    )
    metrics = st.columns(5)
    metrics[0].metric("Trades", len(result.trades))
    metrics[1].metric("Win rate", f"{result.win_rate}%")
    metrics[2].metric("Net P/L", _format_usd(result.total_pnl_usd))
    metrics[3].metric("Total points", f"{result.total_points:+.2f}")
    metrics[4].metric("Max drawdown", _format_usd(-result.max_drawdown_usd))

    extra = st.columns(4)
    extra[0].metric("Wins / losses", f"{result.wins} / {result.losses}")
    extra[1].metric("Avg P/L", _format_usd(result.avg_pnl_usd))
    extra[2].metric("Profit factor", f"{result.profit_factor:.2f}")
    extra[3].metric("Final wallet", _format_usd(result.ending_wallet))
    st.caption(
        f"Starting wallet {_format_usd(result.starting_wallet).replace('+', '')} · "
        "100 lots = 1 ETH → **$1 P/L per 1 ETH point**. Full close at **+5%**. "
        "Same-bar stop and target counts as stop."
    )

    st.markdown("**Trade log**")
    rows = trade_table_rows(result)
    if not rows:
        st.write("No trades in this window (no locked volume bias + pullback).")
        return
    st.dataframe(rows, use_container_width=True, hide_index=True)
