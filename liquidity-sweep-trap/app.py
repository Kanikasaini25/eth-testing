#!/usr/bin/env python3
"""Streamlit UI for Liquidity Sweep / Trap backtesting."""

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
from src.data_fetcher import expected_candles, resolution_from_minutes
from src.pipeline import PipelineResult, run_backtest

st.set_page_config(
    page_title="Liquidity Sweep / Trap",
    page_icon="📉",
    layout="wide",
)

VERDICT_COLORS = {
    "Works": "green",
    "Mixed": "orange",
    "Fails": "red",
    "No trades generated": "gray",
}

ENTRY_TF_MINUTES = 1
MAX_HOLD_CANDLES = 30
ANALYSIS_OPTIONS = {
    "15 min": 15,
    "1 hour": 60,
}


def _verdict_badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "blue")
    return f":{color}[**{verdict}**]"


def _cell(value: object) -> str:
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text


def _render_table(rows: list[dict]) -> None:
    """Render a table without pandas — Streamlit's dataframe path imports pandas."""
    if not rows:
        st.write("No rows.")
        return
    headers = list(rows[0].keys())
    lines = [
        "| " + " | ".join(_cell(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(header, "")) for header in headers) + " |")
    st.markdown("\n".join(lines))


def _trades_table(result: BacktestResult) -> list[dict]:
    return [
        {
            "Side": trade.trade_type,
            "Entry": trade.entry_date,
            "Exit": trade.exit_date,
            "Entry Price": trade.entry_price,
            "Exit Price": trade.exit_price,
            "Swept Liquidity": trade.liquidity_price,
            "Kind": trade.liquidity_kind,
            "Entry Lots": trade.entry_lots,
            "Exit Lots": trade.lots,
            "Points": trade.points,
            "Stop Loss": trade.stop_loss,
            "TP1 (+5)": trade.take_profit_1,
            "TP2 (+15)": trade.take_profit_2,
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
    analysis_label = st.sidebar.selectbox(
        "Analysis timeframe",
        options=list(ANALYSIS_OPTIONS.keys()),
        index=0,
        help="Liquidity is marked on this timeframe. Entry is always 1 minute. Exits: 50 lots at +5 pts, 50 lots at +15 pts.",
    )
    analysis_tf_minutes = ANALYSIS_OPTIONS[analysis_label]
    entry_resolution = resolution_from_minutes(ENTRY_TF_MINUTES)

    days = st.sidebar.slider(
        "Backtest days",
        min_value=1,
        max_value=365,
        value=min(365, int(get_env("BACKTEST_DAYS", "30"))),
        step=1,
    )
    st.sidebar.caption(
        f"**{days} days** → ~**{expected_candles(days, entry_resolution):,}** 1m candles. "
        f"Analysis {analysis_label} / entry 1m / 100 lots, 50% at +5 pts, 50% at +15 pts."
    )

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
        help="Reuse saved CSV when it has enough candles. Re-downloads if cache is too short.",
    )

    run = st.sidebar.button("Run Backtest", type="primary", use_container_width=True)

    return {
        "run": run,
        "symbol": symbol.strip().upper(),
        "days": days,
        "starting_wallet_usd": starting_wallet,
        "base_url": base_url,
        "skip_download": skip_download,
        "parameter_overrides": {
            "analysis_tf_minutes": analysis_tf_minutes,
            "entry_tf_minutes": ENTRY_TF_MINUTES,
            "max_hold_candles": MAX_HOLD_CANDLES,
        },
    }


def render_strategy_summary() -> None:
    st.markdown(
        """
        | Analysis timeframe | Entry timeframe | Typical holding duration |
        |--------------------|-----------------|--------------------------|
        | 15 min – 1 hour | 1 min | 10–30 min |
        """
    )
    st.caption(
        "Find liquidity on 15m–1h → enter 100 lots on 1m after sweep/trap/confirmation → "
        "exit 50 lots at +5 points, remaining 50 lots at +15 points."
    )


def render_overview(pipeline: PipelineResult) -> None:
    result = pipeline.result
    st.subheader("Overview")

    date_from = pipeline.candles[0]["timestamp"][:10] if pipeline.candles else "—"
    date_to = pipeline.candles[-1]["timestamp"][:10] if pipeline.candles else "—"

    cols = st.columns(6)
    cols[0].metric("Symbol", pipeline.symbol)
    cols[1].metric("Requested days", pipeline.days)
    cols[2].metric(f"{pipeline.entry_resolution} candles", len(pipeline.candles))
    cols[3].metric("Sweeps", result.sweeps_detected)
    cols[4].metric("Trades", result.total_trades)
    cols[5].metric("Verdict", result.verdict)

    st.caption(
        f"Data window: **{date_from} → {date_to}** | "
        f"Analysis {pipeline.analysis_tf_minutes}m / entry {pipeline.entry_resolution}"
    )

    st.markdown(
        f"**{result.rule_name}** — {_verdict_badge(result.verdict)} | "
        f"Return: **{result.total_return_pct}%** | "
        f"Buy & hold: **{result.buy_hold_return_pct}%** | "
        f"Win rate: **{result.win_rate}%** | "
        f"Max drawdown: **{result.max_drawdown_pct}%**"
    )

    st.markdown(
        render_price_history(pipeline.candles, pipeline.entry_resolution),
        unsafe_allow_html=True,
    )


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
        "Sweeps Detected": result.sweeps_detected,
        "Confirmed Entries": result.confirmed_entries,
        "Verdict": result.verdict,
    }
    _render_table([summary])

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
    st.markdown(render_trades_on_price(pipeline.candles, result), unsafe_allow_html=True)
    st.caption(
        "Blue = entry, green/red = exit, orange dashed = swept liquidity, "
        "green dashed = +5 pts (50 lots), purple dashed = +15 pts (remaining 50 lots)."
    )


def render_trades(result: BacktestResult) -> None:
    st.subheader("Trade Log")
    if not result.trades:
        st.write("No trades generated.")
        return

    _render_table(_trades_table(result))
    last_wallet = result.trades[-1].wallet_balance
    st.caption(f"Final wallet balance: **${last_wallet:,.2f}**")


def render_report(pipeline: PipelineResult) -> None:
    st.subheader("Full Report")
    st.markdown(pipeline.report_content)

    result = pipeline.result
    st.download_button(
        "Download Markdown Report",
        data=pipeline.report_content,
        file_name=f"{pipeline.symbol}_liquidity_sweep_trap_report.md",
        mime="text/markdown",
    )
    st.download_button(
        "Download JSON Results",
        data=json.dumps([result_to_dict(result)], indent=2),
        file_name=f"{pipeline.symbol}_liquidity_sweep_trap_results.json",
        mime="application/json",
    )


def main() -> None:
    st.title("Liquidity Sweep / Trap")
    st.caption(
        "Independent backtest for the liquidity → sweep/trap → confirmation strategy. "
        "Does not use the parent youtube/ project."
    )

    render_strategy_summary()
    settings = render_sidebar()

    if not settings["run"]:
        st.info("Adjust settings in the sidebar and click **Run Backtest**.")
        st.markdown(
            """
            ### How it works
            1. Mark liquidity on the 15m or 1h chart (swing highs/lows, equal highs/lows, previous highs/lows)
            2. Wait until price reaches that zone on the 1-minute chart — a line is not an entry
            3. Wait for the sweep/trap: wick takes the stops, close comes back inside
            4. Enter only after a 1-minute confirmation candle in the reversal direction
            5. Enter 100 lots. Book 50 lots at +5 points; book remaining 50 lots at +15 points
            6. Stop sits beyond the sweep wick. If neither target hits in 10–30 minutes, flatten the remainder
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
                parameter_overrides=settings["parameter_overrides"],
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
