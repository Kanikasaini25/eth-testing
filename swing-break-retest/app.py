#!/usr/bin/env python3
"""Streamlit UI for 30M Swing Break + 5M Retest backtesting."""

from __future__ import annotations

import json

import streamlit as st

from src.backtest import BacktestResult, result_to_dict
from src.charts import (
    render_cumulative_return_chart,
    render_price_history,
    render_trade_return_bars,
    render_trades_on_price,
    render_win_loss_summary,
)
from src.config import get_env
from src.data_fetcher import expected_5m_candles
from src.pipeline import PipelineResult, run_backtest

st.set_page_config(
    page_title="30M Swing Break + 5M Retest",
    page_icon="📊",
    layout="wide",
)

VERDICT_COLORS = {
    "Works": "green",
    "Mixed": "orange",
    "Fails": "red",
    "No trades generated": "gray",
}


def _verdict_badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "blue")
    return f":{color}[**{verdict}**]"


def _trades_table(result: BacktestResult) -> list[dict]:
    return [
        {
            "Side": trade.trade_type,
            "Entry": trade.entry_date,
            "Exit": trade.exit_date,
            "Entry Price": trade.entry_price,
            "Exit Price": trade.exit_price,
            "Broken Level": trade.broken_level,
            "Stop Loss": trade.stop_loss,
            "Take Profit": trade.take_profit,
            "Return %": trade.return_pct,
            "Wallet (USD)": trade.wallet_balance,
            "Exit Reason": trade.exit_reason,
        }
        for trade in result.trades
    ]


def render_sidebar() -> dict:
    st.sidebar.header("Settings")

    exchange = st.sidebar.selectbox(
        "Delta Exchange",
        options=["India Demo (Testnet)", "India Live", "Global"],
        index=0 if "testnet" in get_env("DELTA_BASE_URL", "").lower() else 1,
    )
    exchange_urls = {
        "India Demo (Testnet)": "https://cdn-ind.testnet.deltaex.org",
        "India Live": "https://api.india.delta.exchange",
        "Global": "https://api.delta.exchange",
    }
    base_url = exchange_urls[exchange]
    default_symbol = "ETHUSD" if exchange != "Global" else "ETHUSDT"

    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", default_symbol))
    days = st.sidebar.slider(
        "Backtest days (5M candles)",
        min_value=1,
        max_value=365,
        value=min(365, int(get_env("BACKTEST_DAYS", "30"))),
        step=1,
        help="Each day = 288 five-minute candles (24 × 12).",
    )
    st.sidebar.caption(f"**{days} days** → ~**{days * 288:,}** 5m candles")

    starting_wallet = st.sidebar.number_input(
        "Starting wallet (USD)",
        min_value=100.0,
        max_value=10_000_000.0,
        value=float(get_env("STARTING_WALLET_USD", "10000")),
        step=100.0,
    )

    skip_download = st.sidebar.checkbox(
        "Use cached OHLCV",
        value=False,
        help="Reuse saved CSV when it has enough candles. Still trims to the selected day count. "
        "Re-downloads automatically if cache is too short.",
    )

    run = st.sidebar.button("Run Backtest", type="primary", use_container_width=True)

    return {
        "run": run,
        "symbol": symbol.strip().upper(),
        "days": days,
        "starting_wallet_usd": starting_wallet,
        "base_url": base_url,
        "skip_download": skip_download,
    }


def render_strategy_summary() -> None:
    st.markdown(
        """
        | 30M Event | 5M Action | Trade |
        |-----------|-----------|-------|
        | Swing High breaks | Retest of Swing High | **LONG** |
        | Swing Low breaks | Retest of Swing Low | **SHORT** |
        | No break | Wait | **NO TRADE** |
        """
    )
    st.caption(
        "Mark 30M swing high/low → wait for break → retest broken level on 5M → "
        "enter in breakout direction. No liquidity concept."
    )


def render_overview(pipeline: PipelineResult) -> None:
    result = pipeline.result
    st.subheader("Overview")

    date_from = pipeline.candles_5m[0]["timestamp"][:10] if pipeline.candles_5m else "—"
    date_to = pipeline.candles_5m[-1]["timestamp"][:10] if pipeline.candles_5m else "—"

    cols = st.columns(6)
    cols[0].metric("Symbol", pipeline.symbol)
    cols[1].metric("Requested days", pipeline.days)
    cols[2].metric("5M candles", len(pipeline.candles_5m))
    cols[3].metric("Breaks", result.breaks_detected)
    cols[4].metric("Trades", result.total_trades)
    cols[5].metric("Verdict", result.verdict)

    st.caption(
        f"Data window: **{date_from} → {date_to}** "
        f"(target {expected_5m_candles(pipeline.days):,} candles for {pipeline.days} days)"
    )

    st.markdown(
        f"**{result.rule_name}** — {_verdict_badge(result.verdict)} | "
        f"Return: **{result.total_return_pct}%** | "
        f"Buy & hold: **{result.buy_hold_return_pct}%** | "
        f"Win rate: **{result.win_rate}%** | "
        f"Max drawdown: **{result.max_drawdown_pct}%**"
    )

    st.markdown(render_price_history(pipeline.candles_5m), unsafe_allow_html=True)


def render_rules(rule: dict) -> None:
    st.subheader("Strategy Rules")
    st.write("**Name:**", rule.get("name", ""))
    st.write("**Type:**", rule.get("strategy_type", ""))

    for section in ("setup_rules", "entry_rules", "exit_rules", "risk_rules"):
        items = rule.get(section, [])
        if not items:
            continue
        st.write(f"**{section.replace('_', ' ').title()}**")
        for item in items:
            st.write(f"- {item}")

    st.write("**Parameters**")
    st.json(rule.get("parameters", {}))


def render_results(result: BacktestResult) -> None:
    st.subheader("Backtest Summary")

    summary = {
        "Technique": result.rule_name,
        "Trades": result.total_trades,
        "Win Rate %": result.win_rate,
        "Strategy Return %": result.total_return_pct,
        "Buy & Hold %": result.buy_hold_return_pct,
        "Max Drawdown %": result.max_drawdown_pct,
        "Avg Return %": result.avg_return_pct,
        "Breaks Detected": result.breaks_detected,
        "Retest Entries": result.retest_entries,
        "Verdict": result.verdict,
    }
    st.dataframe([summary], use_container_width=True)

    metric_cols = st.columns(4)
    metric_cols[0].metric("Strategy Return", f"{result.total_return_pct}%")
    metric_cols[1].metric("Buy & Hold", f"{result.buy_hold_return_pct}%")
    metric_cols[2].metric("Win Rate", f"{result.win_rate}%")
    metric_cols[3].metric("Max Drawdown", f"{result.max_drawdown_pct}%")
    st.markdown(_verdict_badge(result.verdict))

    if result.rule_compliance:
        st.write("**Rule compliance**")
        for key, passed in result.rule_compliance.items():
            icon = "✅" if passed else "❌"
            st.write(f"{icon} {key.replace('_', ' ')}")


def render_charts(pipeline: PipelineResult) -> None:
    result = pipeline.result
    st.subheader("Trade Charts")

    if not result.trades:
        st.write("No trades to chart.")
        return

    st.markdown(render_win_loss_summary(result), unsafe_allow_html=True)
    st.markdown(render_cumulative_return_chart(result), unsafe_allow_html=True)
    st.markdown(render_trade_return_bars(result), unsafe_allow_html=True)
    st.markdown(render_trades_on_price(pipeline.candles_5m, result), unsafe_allow_html=True)
    st.caption(
        "Blue dot = entry, green/red dot = exit, orange dashed line = broken 30M swing level."
    )


def render_trades(result: BacktestResult) -> None:
    st.subheader("Trade Log")
    if not result.trades:
        st.write("No trades generated.")
        return

    st.dataframe(_trades_table(result), use_container_width=True)
    last_wallet = result.trades[-1].wallet_balance
    st.caption(f"Final wallet balance: **${last_wallet:,.2f}**")


def render_report(pipeline: PipelineResult) -> None:
    st.subheader("Full Report")
    st.markdown(pipeline.report_content)

    result = pipeline.result
    st.download_button(
        "Download Markdown Report",
        data=pipeline.report_content,
        file_name=f"{pipeline.symbol}_swing_break_retest_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "Download JSON Results",
        data=json.dumps([result_to_dict(result)], indent=2),
        file_name=f"{pipeline.symbol}_swing_break_retest_results.json",
        mime="application/json",
    )


def main() -> None:
    st.title("30M Swing Break + 5M Retest")
    st.caption(
        "Backtest the swing break and retest strategy on Delta Exchange historical data."
    )

    render_strategy_summary()
    settings = render_sidebar()

    if not settings["run"]:
        st.info("Adjust settings in the sidebar and click **Run Backtest**.")
        st.markdown(
            """
            ### How it works
            1. Download 5M OHLCV from Delta Exchange
            2. Build 30M swing highs/lows from pivots
            3. Detect first break of swing high (long) or swing low (short)
            4. Wait for 5M retest + confirmation candle
            5. Simulate trades with stop loss and take profit
            6. Show results, charts, and downloadable report
            """
        )
        return

    try:
        with st.spinner("Running backtest..."):
            pipeline = run_backtest(
                symbol=settings["symbol"],
                days=settings["days"],
                starting_wallet_usd=settings["starting_wallet_usd"],
                base_url=settings["base_url"],
                skip_download=settings["skip_download"],
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Backtest failed: {exc}")
        return

    st.success("Backtest complete.")

    tab_overview, tab_rules, tab_results, tab_charts, tab_trades, tab_report = st.tabs(
        ["Overview", "Rules", "Results", "Charts", "Trades", "Report"]
    )

    with tab_overview:
        render_overview(pipeline)

    with tab_rules:
        render_rules(pipeline.rule)

    with tab_results:
        render_results(pipeline.result)

    with tab_charts:
        render_charts(pipeline)

    with tab_trades:
        render_trades(pipeline.result)

    with tab_report:
        render_report(pipeline)

    st.caption("_For research only. Past performance does not guarantee future results._")


if __name__ == "__main__":
    main()
