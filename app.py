#!/usr/bin/env python3
"""Streamlit UI for the LQDTY strategy backtester."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import streamlit as st

from src.backtest import BacktestResult
from src.charts import (
    render_cumulative_pnl_chart,
    render_trade_pnl_bars,
    render_trades_on_price,
    render_win_loss_summary,
)
from src.config import STRATEGIES_DIR, get_env
from src.delta_data import CANDLES_PER_DAY_1M, expected_1m_candles
from src.delta_trading import DeltaTradingClient, is_testnet_url
from src.email_notify import is_email_configured, is_email_enabled, send_test_email
from src.live_strategy import LiveLiquidityRunner, default_rules_path
from src.pipeline import run_pipeline

st.set_page_config(
    page_title="Strategy Backtester",
    page_icon="📈",
    layout="wide",
)

VERDICT_COLORS = {
    "Works": "green",
    "Mixed": "orange",
    "Fails": "red",
    "No trades generated": "gray",
}


def _strategy_files() -> list[Path]:
    if not STRATEGIES_DIR.exists():
        return []
    return sorted(STRATEGIES_DIR.glob("*.json"))


def _default_strategy_name() -> str:
    configured = get_env("STRATEGY_RULES")
    if configured:
        return Path(configured).name
    files = _strategy_files()
    return files[0].name if files else ""


def _verdict_badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "blue")
    return f":{color}[**{verdict}**]"


def _results_table(results: list[BacktestResult]) -> list[dict]:
    return [
        {
            "Technique": result.rule_name,
            "Type": result.strategy_type,
            "Trades": result.total_trades,
            "Win Rate %": result.win_rate,
            "Strategy Return %": result.total_return_pct,
            "Buy & Hold %": result.buy_hold_return_pct,
            "Max Drawdown %": result.max_drawdown_pct,
            "Verdict": result.verdict,
        }
        for result in results
    ]


def _format_usd(amount: float) -> str:
    return f"${amount:+,.2f}"


def _trades_table(result: BacktestResult) -> list[dict]:
    rows: list[dict] = []
    for trade in result.trades:
        pnl_usd = trade.pnl_usd
        lot_points = round(trade.points * trade.lots, 2)
        rows.append(
            {
                "Trade": trade.trade_type or _trade_type_from_side(trade.side),
                "Entry": trade.entry_date,
                "Exit": trade.exit_date,
                "Entry Price": trade.entry_price,
                "Exit Price": trade.exit_price,
                "Entry Lots": trade.entry_lots,
                "Exit Lots": trade.lots,
                "Points": trade.points,
                "P/L ($)": _format_usd(pnl_usd),
                "P/L (lot-pts)": lot_points,
                "Return %": trade.return_pct,
                "Wallet": _format_usd(trade.wallet_balance),
                "Exit Reason": trade.exit_reason,
            }
        )
    return rows


def _trades_totals(result: BacktestResult, starting_wallet: float) -> dict[str, float | int]:
    total_lot_points = sum(trade.points * trade.lots for trade in result.trades)
    total_pnl_usd = sum(trade.pnl_usd for trade in result.trades)
    final_wallet = result.trades[-1].wallet_balance if result.trades else starting_wallet
    net_usd = round(final_wallet - starting_wallet, 2)
    wins = losses = 0
    for trade in result.trades:
        if trade.pnl_usd > 0:
            wins += 1
        elif trade.pnl_usd < 0:
            losses += 1
    return {
        "total_lot_points": round(total_lot_points, 2),
        "total_pnl_usd": round(total_pnl_usd, 2),
        "net_usd": net_usd,
        "final_wallet": round(final_wallet, 2),
        "wins": wins,
        "losses": losses,
        "exits": len(result.trades),
    }


def _trades_table_with_total(result: BacktestResult, starting_wallet: float) -> list[dict]:
    rows = _trades_table(result)
    if not rows:
        return rows
    totals = _trades_totals(result, starting_wallet)
    rows.append(
        {
            "Trade": "TOTAL",
            "Entry": "",
            "Exit": "",
            "Entry Price": None,
            "Exit Price": None,
            "Entry Lots": None,
            "Exit Lots": None,
            "Points": None,
            "P/L ($)": _format_usd(totals["net_usd"]),
            "P/L (lot-pts)": totals["total_lot_points"],
            "Return %": None,
            "Wallet": _format_usd(totals["final_wallet"]),
            "Exit Reason": "",
        }
    )
    return rows


def _trade_type_from_side(side: str) -> str:
    if side == "long":
        return "Buy"
    if side == "short":
        return "Sell"
    return "—"


def render_sidebar() -> dict:
    st.sidebar.header("Settings")

    strategy_files = _strategy_files()
    strategy_names = [path.name for path in strategy_files]
    selected_strategy = ""
    if strategy_names:
        default_name = _default_strategy_name()
        default_index = (
            strategy_names.index(default_name) if default_name in strategy_names else 0
        )
        selected_strategy = st.sidebar.selectbox(
            "Strategy rules",
            options=strategy_names,
            index=default_index,
            help="JSON files in data/strategies/",
        )
    else:
        st.sidebar.warning("No strategy JSON files in data/strategies/")

    exchange = st.sidebar.selectbox(
        "Delta Exchange",
        options=["India Demo (Testnet)", "India Live", "Global"],
        index=(
            0
            if "testnet" in get_env("DELTA_BASE_URL", "").lower()
            else 1
        ),
    )
    exchange_urls = {
        "India Demo (Testnet)": "https://cdn-ind.testnet.deltaex.org",
        "India Live": "https://api.india.delta.exchange",
        "Global": "https://api.delta.exchange",
    }
    base_url = exchange_urls[exchange]
    default_symbol = "ETHUSD" if exchange != "Global" else "ETHUSDT"

    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", default_symbol))
    resolution = st.sidebar.selectbox(
        "Timeframe",
        options=["1d", "4h", "1h", "15m"],
        index=0,
    )
    days = st.sidebar.slider(
        "Backtest days (1d lines + 1m entries)",
        min_value=1,
        max_value=365,
        value=min(365, int(get_env("BACKTEST_DAYS", "30"))),
        step=1,
        help=f"Same period for daily liquidity lines and 1m execution. "
        f"1 day = {CANDLES_PER_DAY_1M} one-minute candles.",
    )
    st.sidebar.caption(
        f"**{days} days** → ~**{expected_1m_candles(days):,}** 1m candles "
        f"({CANDLES_PER_DAY_1M} per day)"
    )
    starting_wallet = st.sidebar.number_input(
        "Starting wallet (USD)",
        min_value=100.0,
        max_value=10_000_000.0,
        value=float(get_env("STARTING_WALLET_USD", "10000")),
        step=100.0,
        help="Simulated account size; wallet column updates after each exit.",
    )
    run = st.sidebar.button("Run Analysis", type="primary", use_container_width=True)

    return {
        "run": run,
        "rules_path": str(STRATEGIES_DIR / selected_strategy) if selected_strategy else "",
        "symbol": symbol.strip().upper(),
        "resolution": resolution,
        "days": days,
        "starting_wallet_usd": starting_wallet,
        "base_url": base_url,
    }


def render_overview(result) -> None:
    st.subheader("Overview")

    cols = st.columns(5)
    cols[0].metric("Strategy", result.strategy_id)
    cols[1].metric("Daily candles", len(result.ohlcv))
    if result.intraday_ohlcv:
        expected = expected_1m_candles(result.backtest_days)
        cols[2].metric(
            "1m candles",
            len(result.intraday_ohlcv),
            delta=f"target {expected:,}",
            delta_color="off",
        )
    else:
        cols[2].metric("1m candles", "—")
    cols[3].metric("Techniques", len(result.rules))
    cols[4].metric("Strategies tested", len(result.results))

    if result.intraday_ohlcv:
        st.caption(
            f"Backtest window: **{result.backtest_days} days** — "
            f"1m data = {result.backtest_days} × {CANDLES_PER_DAY_1M} = "
            f"**{expected_1m_candles(result.backtest_days):,}** candles max"
        )

    for backtest in result.results:
        st.markdown(
            f"**{backtest.rule_name}** — {_verdict_badge(backtest.verdict)} | "
            f"Return: **{backtest.total_return_pct}%** | "
            f"Win rate: **{backtest.win_rate}%** | "
            f"Trades: **{backtest.total_trades}**"
        )


def render_price_chart(ohlcv: list[dict]) -> None:
    st.subheader("ETH Price History")
    closes = [float(row["close"]) for row in ohlcv]
    if not closes:
        st.write("No price data available.")
        return

    width, height = 900, 220
    min_price = min(closes)
    max_price = max(closes)
    price_range = max(max_price - min_price, 1e-9)

    points: list[str] = []
    for index, price in enumerate(closes):
        x = (index / max(len(closes) - 1, 1)) * width
        y = height - ((price - min_price) / price_range) * (height - 20) - 10
        points.append(f"{x:.1f},{y:.1f}")

    svg = f"""
    <svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">
      <polyline fill="none" stroke="#1f77b4" stroke-width="2"
        points="{" ".join(points)}" />
      <text x="0" y="12" fill="#666" font-size="12">${max_price:,.2f}</text>
      <text x="0" y="{height - 4}" fill="#666" font-size="12">${min_price:,.2f}</text>
    </svg>
    """
    st.markdown(svg, unsafe_allow_html=True)
    st.caption(f"{ohlcv[0]['timestamp'][:10]} → {ohlcv[-1]['timestamp'][:10]}")


def render_demo_account(symbol: str, base_url: str) -> None:
    st.subheader("Delta Demo / Live Account")
    env_label = "Demo (Testnet)" if is_testnet_url(base_url) else "Production"
    st.caption(f"Environment: **{env_label}** · `{base_url}` · Symbol: **{symbol}**")

    client = DeltaTradingClient(base_url=base_url, symbol=symbol)
    if not client.is_configured:
        st.warning("Add `DELTA_API_KEY` and `DELTA_API_SECRET` to your `.env` file.")
        return

    if st.button("Test connection", type="primary", key="test_delta_connection"):
        with st.spinner("Connecting to Delta Exchange..."):
            st.session_state["delta_snapshot"] = client.test_connection()
            st.session_state.pop("delta_order_result", None)

    btn_col1, btn_col2 = st.columns(2)
    with btn_col1:
        if st.button(
            "Place test BUY (100 lots @ market)",
            key="place_test_buy",
            disabled=not client.is_configured,
        ):
            with st.spinner("Placing 100-lot buy order..."):
                order_result = client.place_buy_at_current_price(size=100)
                st.session_state["delta_order_result"] = order_result
                st.session_state["delta_snapshot"] = client.test_connection()
    with btn_col2:
        if st.button(
            "Exit open position @ market",
            key="exit_open_position",
            disabled=not client.is_configured,
        ):
            with st.spinner("Closing open position..."):
                order_result = client.close_position_at_market()
                st.session_state["delta_order_result"] = order_result
                st.session_state["delta_snapshot"] = client.test_connection()

    snapshot = st.session_state.get("delta_snapshot")
    order_result = st.session_state.get("delta_order_result")
    if order_result is not None:
        if order_result.success:
            action = "BUY" if order_result.side == "buy" else "SELL"
            st.success(
                f"{action} order placed: **{order_result.size} lots** "
                f"({order_result.order_type}) near **${order_result.price:,.2f}**"
            )
            if order_result.order:
                st.json(order_result.order)
        else:
            st.error(f"Order failed: {order_result.error}")

    if snapshot is None:
        st.info("Click **Test connection** to load wallet balance and open positions.")
        return

    if not snapshot.connected:
        st.error(f"Connection failed: {snapshot.error}")
        st.markdown(
            "**Checklist:**\n"
            "- Demo keys must use `https://cdn-ind.testnet.deltaex.org`\n"
            "- Live keys must use `https://api.india.delta.exchange`\n"
            "- Whitelist your IP in Delta API settings\n"
            "- Enable **Read** + **Trade** permissions"
        )
        return

    st.success("Connected to Delta Exchange")

    cols = st.columns(3)
    cols[0].metric("Product ID", snapshot.product_id or "—")
    if snapshot.ticker:
        cols[1].metric("Mark price", snapshot.ticker.get("mark_price", "—"))
    cols[2].metric("Symbol", snapshot.symbol)

    st.markdown("**Wallet balances**")
    if snapshot.wallet_balances:
        wallet_rows = [
            {
                "Asset": w.get("asset_symbol") or w.get("asset_id"),
                "Balance": w.get("balance"),
                "Available": w.get("available_balance"),
            }
            for w in snapshot.wallet_balances
        ]
        st.dataframe(wallet_rows, use_container_width=True)
    else:
        st.write("No wallet data returned.")

    st.markdown("**Open position**")
    if snapshot.position:
        st.json(snapshot.position)
    else:
        st.write("No open position for this symbol.")

    st.markdown("**Trading API (ready)**")
    st.code(
        "client.place_market_order(size=100, side='buy')   # 100 lots long\n"
        "client.place_market_order(size=80, side='sell', reduce_only=True)  # partial exit\n"
        "client.place_stop_order(size=100, side='sell', stop_price=...)  # stop loss",
        language="python",
    )


def render_live_strategy(symbol: str, base_url: str) -> None:
    st.subheader("LQDTY Live Strategy → Demo Account")
    env_label = "Demo (Testnet)" if is_testnet_url(base_url) else "Production"
    st.caption(
        f"Runs the same liquidity rules as backtest on **{env_label}**. "
        "Long and short · body ≥ 75% · entry within 8 pts of the liquidity line · "
        "min R:R 2.5 · 100 lots · 80 partial @ +15 pts · 20 runner with 3 pt trail."
    )

    rules_path = default_rules_path()
    if not rules_path.exists():
        st.warning("Add a strategy JSON file under `data/strategies/` to run live.")
        return

    runner = LiveLiquidityRunner(symbol=symbol, base_url=base_url)
    state = runner.state

    enabled = st.toggle(
        "Strategy enabled",
        value=state.enabled,
        key="live_strategy_enabled",
        help="When enabled, each tick scans for LQDTY signals and manages open positions.",
    )
    if enabled != state.enabled:
        runner.set_enabled(enabled)

    params = runner.rule.parameters
    st.markdown("**Active live rules**")
    st.json(
        {
            "allow_longs": params.get("allow_longs", True),
            "allow_shorts": params.get("allow_shorts", True),
            "min_signal_body_ratio": params.get("min_signal_body_ratio"),
            "max_entry_distance_from_line_points": params.get(
                "max_entry_distance_from_line_points"
            ),
            "min_reward_to_risk": params.get("min_reward_to_risk"),
            "min_stop_loss_points": params.get("min_stop_loss_points"),
            "max_stop_loss_points": params.get("max_stop_loss_points"),
            "partial_target_points": params.get("partial_target_points"),
            "session_hours_utc": (
                f"{params.get('session_start_hour_utc')}:00–"
                f"{params.get('session_end_hour_utc')}:00"
            ),
        }
    )

    tick_col1, tick_col2, tick_col3 = st.columns(3)
    with tick_col1:
        run_live = st.button("Run strategy tick", type="primary", key="run_live_tick")
    with tick_col2:
        dry_run = st.checkbox("Dry run (no orders)", key="live_dry_run")
    with tick_col3:
        st.caption(f"Rules: `{rules_path.name}`")

    if run_live:
        with st.spinner("Running live strategy tick..."):
            tick_result = runner.tick(dry_run=dry_run)
            st.session_state["live_tick_result"] = tick_result
            st.session_state["live_runner_state"] = runner.state

    tick_result = st.session_state.get("live_tick_result")
    if tick_result is not None:
        if tick_result.success:
            st.success("Tick completed")
            for action in tick_result.actions:
                st.write(f"- {action}")
        else:
            st.error(f"Tick failed: {tick_result.error}")

    state = st.session_state.get("live_runner_state", runner.state)
    level_col1, level_col2, level_col3, level_col4 = st.columns(4)
    level_col1.metric("Upper line (prev day high)", state.upper_level or "—")
    level_col2.metric("Lower line (prev day low)", state.lower_level or "—")
    if tick_result and tick_result.mark_price:
        level_col3.metric("Mark price", f"${tick_result.mark_price:,.2f}")
    level_col4.metric("Exchange position", tick_result.exchange_position if tick_result else "—")

    st.markdown("**Session state**")
    st.json(
        {
            "enabled": state.enabled,
            "touched_upper": state.session.touched_upper,
            "touched_lower": state.session.touched_lower,
            "trades_in_sequence": state.session.trades_in_sequence,
            "full_sl_count": state.session.full_sl_count,
            "upper_line_blocked": state.session.upper_line_blocked,
            "lower_line_blocked": state.session.lower_line_blocked,
            "last_processed_ts": state.session.last_processed_ts,
        }
    )

    st.markdown("**Tracked position**")
    if state.position:
        st.json(asdict(state.position))
    else:
        st.write("Flat — waiting for LQDTY entry signal.")

    st.markdown("**Recent logs**")
    if state.logs:
        for entry in reversed(state.logs[-15:]):
            st.caption(entry)
    else:
        st.write("No live actions yet.")

    st.markdown("**Email alerts**")
    if is_email_configured():
        st.success(f"SMTP enabled → alerts go to `{get_env('NOTIFY_EMAIL')}`")
        if st.button("Send test email", key="send_test_email"):
            with st.spinner("Sending test email..."):
                result = send_test_email()
            if result.success:
                st.success(result.message)
            else:
                st.error(result.message)
    elif is_email_enabled():
        st.warning("Email enabled but SMTP settings incomplete. Update `.env` file.")
    else:
        st.info("Set `EMAIL_NOTIFY_ENABLED=true` and SMTP settings in `.env` for entry alerts.")

    st.info(
        "Click **Run strategy tick** every minute (or use "
        "`python scripts/run_live_strategy.py --loop`) to keep the strategy running."
    )


def main() -> None:
    st.title("Strategy Backtester")
    st.caption(
        "Backtest strategy rules from JSON on Delta Exchange ETH futures historical data."
    )

    settings = render_sidebar()

    demo_tab, live_tab, backtest_tab = st.tabs(
        ["Demo Account", "Live Strategy", "Backtest"]
    )

    with demo_tab:
        render_demo_account(settings["symbol"], settings["base_url"])

    with live_tab:
        render_live_strategy(settings["symbol"], settings["base_url"])

    with backtest_tab:
        _render_backtest_page(settings)


def _render_backtest_page(settings: dict) -> None:
    if not settings["run"]:
        st.info("Select a strategy in the sidebar and click **Run Analysis**.")
        st.markdown(
            """
            ### How it works
            1. Load trading rules from `data/strategies/*.json`
            2. Download Delta Exchange OHLCV data
            3. Backtest each technique on historical data
            4. Show results and downloadable report
            """
        )
        return

    if not settings["rules_path"]:
        st.error("Add a strategy JSON file under `data/strategies/` first.")
        return

    try:
        with st.spinner("Running pipeline..."):
            result = run_pipeline(
                rules_path=settings["rules_path"],
                symbol=settings["symbol"],
                resolution=settings["resolution"],
                days=settings["days"],
                starting_wallet_usd=settings["starting_wallet_usd"],
                base_url=settings["base_url"],
            )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Pipeline failed: {exc}")
        return

    st.success("Analysis complete.")

    tab_overview, tab_rules, tab_results, tab_charts, tab_trades, tab_report = st.tabs(
        ["Overview", "Rules", "Results", "Charts", "Trades", "Report"]
    )

    with tab_overview:
        render_overview(result)
        render_price_chart(result.ohlcv)

    with tab_rules:
        st.subheader("Strategy Rules")
        if not result.rules:
            st.warning("No rules found in this strategy file.")
        for rule in result.rules:
            with st.expander(rule.name, expanded=True):
                st.write("**Type:**", rule.strategy_type)
                if rule.setup_rules:
                    st.write("**Setup rules**")
                    for item in rule.setup_rules:
                        st.write(f"- {item}")
                st.write("**Entry rules**")
                for entry in rule.entry_rules:
                    st.write(f"- {entry}")
                st.write("**Exit rules**")
                for exit_rule in rule.exit_rules:
                    st.write(f"- {exit_rule}")
                if rule.risk_rules:
                    st.write("**Risk rules**")
                    for item in rule.risk_rules:
                        st.write(f"- {item}")
                st.write("**Parameters**")
                st.json(rule.parameters)

    with tab_results:
        st.subheader("Backtest Summary")
        st.dataframe(_results_table(result.results), use_container_width=True)

        compare_cols = st.columns(len(result.results))
        for index, backtest in enumerate(result.results):
            with compare_cols[index]:
                st.metric("Technique", backtest.rule_name)
                st.metric("Backtest mode", backtest.backtest_mode)
                st.metric("Strategy Return", f"{backtest.total_return_pct}%")
                st.metric("Buy & Hold", f"{backtest.buy_hold_return_pct}%")
                st.metric("Win Rate", f"{backtest.win_rate}%")
                st.markdown(_verdict_badge(backtest.verdict))
                if backtest.rule_compliance:
                    st.write("**Rule compliance**")
                    for key, passed in backtest.rule_compliance.items():
                        icon = "✅" if passed else "❌"
                        st.write(f"{icon} {key.replace('_', ' ')}")

    with tab_charts:
        st.subheader("Trade Result Charts")
        for backtest in result.results:
            with st.expander(f"{backtest.rule_name}", expanded=True):
                if not backtest.trades:
                    st.write("No trades to chart.")
                    continue

                st.markdown(
                    render_win_loss_summary(backtest),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    render_cumulative_pnl_chart(backtest),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    render_trade_pnl_bars(backtest),
                    unsafe_allow_html=True,
                )
                st.markdown(
                    render_trades_on_price(result.ohlcv, backtest),
                    unsafe_allow_html=True,
                )
                st.caption(
                    "P/L charts use net USD (100 lots = 1 ETH → ~$1 per $1 ETH move, fees included). "
                    "Blue dot = entry, green/red dot = exit."
                )

    with tab_trades:
        st.subheader("Trade Log")
        starting_wallet = settings["starting_wallet_usd"]
        for backtest in result.results:
            with st.expander(f"{backtest.rule_name} ({len(backtest.trades)} exits)", expanded=True):
                if backtest.trades:
                    totals = _trades_totals(backtest, starting_wallet)
                    st.dataframe(
                        _trades_table_with_total(backtest, starting_wallet),
                        use_container_width=True,
                    )
                    pnl_col1, pnl_col2, pnl_col3, pnl_col4 = st.columns(4)
                    pnl_col1.metric(
                        "Total P/L",
                        _format_usd(totals["net_usd"]),
                        help=f"Net profit/loss vs starting {_format_usd(starting_wallet)}",
                    )
                    pnl_col2.metric(
                        "Final wallet",
                        _format_usd(totals["final_wallet"]),
                    )
                    pnl_col3.metric("Winning exits", totals["wins"])
                    pnl_col4.metric("Losing exits", totals["losses"])
                    st.caption(
                        f"Starting wallet: **{_format_usd(starting_wallet)}** → "
                        f"Final: **{_format_usd(totals['final_wallet'])}** · "
                        f"**P/L ($)** = net USD per exit (price move × ETH size − entry/exit fees)"
                    )
                else:
                    st.write("No trades generated.")

    with tab_report:
        st.subheader("Full Report")
        st.markdown(result.report_content)
        st.download_button(
            "Download Markdown Report",
            data=result.report_content,
            file_name=f"{result.strategy_id}_report.md",
            mime="text/markdown",
        )
        st.download_button(
            "Download JSON Results",
            data=json.dumps([asdict(item) for item in result.results], indent=2),
            file_name=f"{result.strategy_id}_results.json",
            mime="application/json",
        )

    st.caption("_For research only. Past performance does not guarantee future results._")


if __name__ == "__main__":
    main()
