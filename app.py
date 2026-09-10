#!/usr/bin/env python3
"""Streamlit UI for the ETH India volume-bias live strategy."""

from __future__ import annotations

from dataclasses import asdict

import streamlit as st

from src.config import get_env
from src.delta_trading import DeltaTradingClient
from src.email_notify import is_email_configured, is_email_enabled, send_test_email
from src.live_strategy import LiveEthVolumeRunner
from src.timezone import india_now
from src.ui_backtest import render_backtest_tab

st.set_page_config(
    page_title="ETH Volume-Bias Strategy",
    page_icon="📈",
    layout="wide",
)


def render_sidebar() -> dict:
    st.sidebar.header("Account")
    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD"))
    base_url = get_env("DELTA_BASE_URL", "https://api.india.delta.exchange")
    st.sidebar.caption(f"Trade: `{base_url}`")
    return {"symbol": symbol.strip().upper(), "base_url": base_url}


def render_live_account(symbol: str, base_url: str) -> None:
    st.subheader("Delta Live Account")
    st.caption(f"`{base_url}` · Symbol: **{symbol}**")

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
        if st.button("Place test BUY (100 lots @ market)", key="place_test_buy"):
            with st.spinner("Placing 100-lot buy order..."):
                st.session_state["delta_order_result"] = client.place_buy_at_current_price(size=100)
                st.session_state["delta_snapshot"] = client.test_connection()
    with btn_col2:
        if st.button("Exit open position @ market", key="exit_open_position"):
            with st.spinner("Closing open position..."):
                st.session_state["delta_order_result"] = client.close_position_at_market()
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
            "- Live keys must use `https://api.india.delta.exchange`\n"
            "- Global keys must use `https://api.delta.exchange`\n"
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
        st.dataframe(
            [
                {
                    "Asset": wallet.get("asset_symbol") or wallet.get("asset_id"),
                    "Balance": wallet.get("balance"),
                    "Available": wallet.get("available_balance"),
                }
                for wallet in snapshot.wallet_balances
            ],
            use_container_width=True,
        )
    else:
        st.write("No wallet data returned.")

    st.markdown("**Open position**")
    if snapshot.position:
        st.json(snapshot.position)
    else:
        st.write("No open position for this symbol.")


def render_live_strategy(symbol: str) -> None:
    st.subheader("ETH India Volume-Bias Strategy")
    st.caption(
        "Watch India-live ETH volume all day (buy vs sell). At **7:00 PM IST**, wait for "
        "**one 15m pullback**, then a **1m confirmation** candle with the day's power. "
        "Stop = 15m pullback wick. Close full at **+5%**. Trail: +1% keep SL, "
        "+2%→SL +1%, +3%→SL +2%, +4%→SL +3%. After **2 wins** or **2 losses**, stop for the day."
    )

    runner = LiveEthVolumeRunner(symbol=symbol)
    st.caption(
        f"Data: `{runner.data_base_url}` · Trade: `{runner.base_url}` · "
        f"Entry hour: `{runner.entry_hour_ist:02d}:00 IST` · "
        f"Now: `{india_now().strftime('%Y-%m-%d %H:%M IST')}`"
    )
    state = runner.state

    enabled = st.toggle(
        "Strategy enabled",
        value=state.enabled,
        key="live_strategy_enabled",
        help="When enabled, each tick updates volume bias and can place the 7pm pullback order.",
    )
    if enabled != state.enabled:
        runner.set_enabled(enabled)

    tick_col1, tick_col2, tick_col3 = st.columns(3)
    with tick_col1:
        run_live = st.button("Run strategy tick", type="primary", key="run_live_tick")
    with tick_col2:
        dry_run = st.checkbox("Dry run (no orders)", key="live_dry_run")
    with tick_col3:
        st.caption(
            f"{runner.position_lots} lots · {runner.pullback_resolution} pullback · "
            f"{runner.entry_resolution} confirmation"
        )

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
    bias_label = {"long": "BUY", "short": "SELL"}.get(state.session.bias, "—")
    metric_cols = st.columns(4)
    metric_cols[0].metric("Buy volume", f"{state.session.buy_volume:.4f}")
    metric_cols[1].metric("Sell volume", f"{state.session.sell_volume:.4f}")
    metric_cols[2].metric("Day market power", bias_label)
    if tick_result and tick_result.mark_price:
        metric_cols[3].metric("Mark price", f"${tick_result.mark_price:,.2f}")
    else:
        metric_cols[3].metric("Exchange position", tick_result.exchange_position if tick_result else "—")

    st.markdown("**Session state**")
    st.json(
        {
            "enabled": state.enabled,
            "india_day": state.session.day,
            "bias": state.session.bias,
            "bias_locked": state.session.bias_locked,
            "traded_today": state.session.traded_today,
            "wins_today": state.session.wins_today,
            "losses_today": state.session.losses_today,
            "after_pullback_ts": state.session.after_pullback_ts,
            "pullback": state.session.pullback,
            "last_processed_ts": state.session.last_processed_ts,
        }
    )

    st.markdown("**Tracked position**")
    if state.position:
        st.json(asdict(state.position))
    else:
        st.write(
            "Flat — after a stop or +5% close, waits for the next 15m pullback + 1m confirmation. "
            "Stops for the day after **2 wins** or **2 losses**."
        )

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
    st.title("ETH Volume-Bias Strategy")
    st.caption("India-live ETH volume all day → 15m pullback at 7:00 PM IST → 1m confirmation → 5% trail.")
    settings = render_sidebar()
    live_account_tab, live_strategy_tab, backtest_tab = st.tabs(
        ["Live Account", "Live Strategy", "Backtest"]
    )
    with live_account_tab:
        render_live_account(settings["symbol"], settings["base_url"])
    with live_strategy_tab:
        render_live_strategy(settings["symbol"])
    with backtest_tab:
        render_backtest_tab(settings["symbol"])


if __name__ == "__main__":
    main()
