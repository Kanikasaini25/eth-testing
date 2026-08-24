"""
Streamlit UI for the standalone "1H Liquidity Reversal" ETH strategy.

Strategy details, parameters, backtesting, charts, trade log, and debug events.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import streamlit as st

from src.backtest import BacktestResult, result_to_dict
from src.charts import (
    render_cumulative_pnl_chart,
    render_trade_pnl_bars,
    render_trades_on_price,
    render_win_loss_summary,
)
from src.config import OHLCV_DIR, REPORTS_DIR, ensure_data_dirs, get_env
from src.delta_data import (
    CANDLES_PER_DAY_1M,
    DeltaExchangeClient,
    expected_1m_candles,
    load_ohlcv,
    save_ohlcv,
    trim_ohlcv_to_days,
)
from src.strategies.liquidity_reversal_1h import (
    STRATEGY_NAME,
    TAKE_PROFIT_POINTS,
    backtest_1h_liquidity_reversal,
    build_strategy_rule,
)

VERDICT_COLORS = {
    "Works": "green",
    "Mixed": "orange",
    "Fails": "red",
    "No trades generated": "gray",
}

HISTORY_URL_INDIA = "https://api.india.delta.exchange"


def _verdict_badge(verdict: str) -> str:
    color = VERDICT_COLORS.get(verdict, "blue")
    return f":{color}[**{verdict}**]"


def _format_usd(amount: float) -> str:
    return f"${amount:+,.2f}"


def _trade_type_from_side(side: str) -> str:
    if side == "long":
        return "Buy"
    if side == "short":
        return "Sell"
    return "—"


def _trades_table(result: BacktestResult) -> list[dict]:
    rows: list[dict] = []
    for trade in result.trades:
        rows.append(
            {
                "Trade": trade.trade_type or _trade_type_from_side(trade.side),
                "Entry": trade.entry_date,
                "Exit": trade.exit_date,
                "Entry Price": trade.entry_price,
                "Exit Price": trade.exit_price,
                "Lots": trade.lots,
                "Points": trade.points,
                "P/L ($)": _format_usd(trade.pnl_usd),
                "Return %": trade.return_pct,
                "Wallet": _format_usd(trade.wallet_balance),
                "Exit Reason": trade.exit_reason,
            }
        )
    return rows


def _trades_totals(result: BacktestResult, starting_wallet: float) -> dict[str, float | int]:
    final_wallet = result.trades[-1].wallet_balance if result.trades else starting_wallet
    wins = sum(1 for t in result.trades if t.pnl_usd > 0)
    losses = sum(1 for t in result.trades if t.pnl_usd < 0)
    return {
        "net_usd": round(final_wallet - starting_wallet, 2),
        "final_wallet": round(final_wallet, 2),
        "wins": wins,
        "losses": losses,
        "total_points": round(sum(t.points for t in result.trades), 2),
    }


def _history_base_url(ui_base_url: str) -> str:
    if "testnet" in ui_base_url.lower():
        return HISTORY_URL_INDIA
    return ui_base_url.rstrip("/") or HISTORY_URL_INDIA


def render_sidebar_settings() -> dict[str, Any]:
    st.sidebar.header("1H Liquidity Reversal")
    st.sidebar.caption("ETH only · 1H swings + 1m confirmation")

    exchange = st.sidebar.selectbox(
        "Delta Exchange (history)",
        options=["India Live", "Global"],
        index=0,
        key="lr1h_exchange",
        help="Historical candles use the public history API (not testnet).",
    )
    exchange_urls = {
        "India Live": HISTORY_URL_INDIA,
        "Global": "https://api.delta.exchange",
    }
    base_url = exchange_urls[exchange]
    default_symbol = "ETHUSD" if exchange == "India Live" else "ETHUSDT"

    symbol = st.sidebar.text_input(
        "Symbol",
        value=get_env("DELTA_SYMBOL", default_symbol),
        key="lr1h_symbol",
    )
    days = st.sidebar.slider(
        "Backtest days (1m window)",
        min_value=1,
        max_value=60,
        value=min(14, int(get_env("BACKTEST_DAYS", "7"))),
        step=1,
        key="lr1h_days",
        help=f"1 day ≈ {CANDLES_PER_DAY_1M} one-minute candles. Extra 1H history is fetched automatically.",
    )
    st.sidebar.caption(
        f"**{days} days** → ~**{expected_1m_candles(days):,}** 1m candles"
    )

    starting_wallet = st.sidebar.number_input(
        "Starting wallet (USD)",
        min_value=100.0,
        max_value=10_000_000.0,
        value=float(get_env("STARTING_WALLET_USD", "10000")),
        step=100.0,
        key="lr1h_wallet",
    )
    swing_strength = st.sidebar.slider(
        "1H swing strength",
        min_value=1,
        max_value=5,
        value=2,
        key="lr1h_swing",
        help="Fractal bars left/right required to confirm a swing high/low.",
    )
    confirmation_timeout = st.sidebar.number_input(
        "Confirmation timeout (1m bars)",
        min_value=0,
        max_value=1440,
        value=120,
        step=10,
        key="lr1h_timeout",
        help="Max bars after a sweep to wait for 2-candle confirmation. 0 = no timeout.",
    )
    tp_points = st.sidebar.number_input(
        "Partial TP (points)",
        min_value=1.0,
        max_value=100.0,
        value=float(TAKE_PROFIT_POINTS),
        step=1.0,
        key="lr1h_tp",
        help="Book 80 lots at this profit. Remaining 20 lots use trailing stop.",
    )
    trailing_points = st.sidebar.number_input(
        "Trailing stop (points)",
        min_value=0.5,
        max_value=50.0,
        value=3.0,
        step=0.5,
        key="lr1h_trail",
        help="After partial, trail the 20-lot runner by this many points from best price.",
    )
    position_lots = st.sidebar.number_input(
        "Position lots",
        min_value=1,
        max_value=10_000,
        value=100,
        step=1,
        key="lr1h_lots",
    )
    st.sidebar.caption("Exit split: **80 lots** at partial TP · **20 lots** trailing runner")
    fee_pct = st.sidebar.number_input(
        "Fee % per side",
        min_value=0.0,
        max_value=1.0,
        value=0.05,
        step=0.01,
        key="lr1h_fee",
        format="%.2f",
    )
    use_cache = st.sidebar.checkbox(
        "Reuse cached OHLCV if available",
        value=True,
        key="lr1h_cache",
    )
    show_debug = st.sidebar.checkbox(
        "Capture debug events",
        value=True,
        key="lr1h_debug",
    )

    run = st.sidebar.button(
        "Run Backtest",
        type="primary",
        use_container_width=True,
        key="lr1h_run",
    )

    return {
        "run": run,
        "symbol": symbol.strip().upper(),
        "days": int(days),
        "starting_wallet_usd": float(starting_wallet),
        "swing_strength": int(swing_strength),
        "confirmation_timeout_bars": int(confirmation_timeout),
        "take_profit_points": float(tp_points),
        "trailing_stop_points": float(trailing_points),
        "position_lots": int(position_lots),
        "partial_exit_lots": 80,
        "runner_lots": 20,
        "fee_pct_per_side": float(fee_pct),
        "base_url": base_url,
        "use_cache": use_cache,
        "show_debug": show_debug,
    }


def render_strategy_details() -> None:
    st.subheader("Strategy overview")
    st.markdown(
        f"""
**{STRATEGY_NAME}** trades ETH using locked **1-hour swing liquidity**, a **liquidity sweep**,
then a **1-minute two-candle reversal** confirmation.

| Piece | Rule |
|-------|------|
| Liquidity | Confirmed 1H Swing High / Swing Low (locked, not moved) |
| Trigger | Price sweeps beyond one locked level |
| Confirmation | 1m: two same-color candles; 2nd breaks 1st extreme |
| Entry | Break of first confirmation candle high (long) / low (short) |
| Stop loss | Wick of the **first** confirmation candle (until partial) |
| Take profit | At **+{int(TAKE_PROFIT_POINTS)}** points → book **80 lots** |
| Runner | Keep **20 lots** with a **3-point trailing stop** |
| Risk | One trade at a time · no EMA/RSI/MACD/Bollinger |
"""
    )

    col_long, col_short = st.columns(2)
    with col_long:
        st.markdown("#### LONG flow")
        st.code(
            "1H Swing Low\n"
            "  → price sweeps below Swing Low\n"
            "  → 1m First Green (C > O)\n"
            "  → 1m Second Green\n"
            "  → Second High > First High\n"
            "  → ENTRY @ First Green High\n"
            "  → SL = First Green Low\n"
            f"  → +{int(TAKE_PROFIT_POINTS)} pts → book 80 lots\n"
            "  → 20 lots runner + 3pt trailing SL",
            language="text",
        )
    with col_short:
        st.markdown("#### SHORT flow")
        st.code(
            "1H Swing High\n"
            "  → price sweeps above Swing High\n"
            "  → 1m First Red (C < O)\n"
            "  → 1m Second Red\n"
            "  → Second Low < First Low\n"
            "  → ENTRY @ First Red Low\n"
            "  → SL = First Red High\n"
            f"  → +{int(TAKE_PROFIT_POINTS)} pts → book 80 lots\n"
            "  → 20 lots runner + 3pt trailing SL",
            language="text",
        )

    with st.expander("Multi-timeframe sync & anti look-ahead", expanded=False):
        st.markdown(
            """
1. 1H fractal swings need `strength` bars on both sides before they exist.
2. At each 1m bar time `T`, only fully closed 1H candles (`open ≤ T − 1h`) are used.
3. After levels lock, they stay fixed until the setup cycle ends (trade or timeout).
4. Sweep must occur **before** any 1m confirmation candles are accepted.
5. Entry uses the break price of the first confirmation candle on the second candle.
            """
        )


def render_rules_panel(rule) -> None:
    st.subheader("Rules & parameters")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Setup**")
        for item in rule.setup_rules:
            st.write(f"- {item}")
        st.markdown("**Entry**")
        for item in rule.entry_rules:
            st.write(f"- {item}")
    with c2:
        st.markdown("**Exit**")
        for item in rule.exit_rules:
            st.write(f"- {item}")
        st.markdown("**Risk**")
        for item in rule.risk_rules:
            st.write(f"- {item}")
    st.markdown("**Parameters**")
    st.json(rule.parameters)


def _load_or_fetch_ohlcv(settings: dict[str, Any]) -> tuple[list[dict], list[dict], str]:
    ensure_data_dirs()
    symbol = settings["symbol"]
    days = settings["days"]
    hour_days = days + 5
    minute_path = OHLCV_DIR / f"{symbol}_1m.csv"
    hour_path = OHLCV_DIR / f"{symbol}_1h.csv"
    notes: list[str] = []

    can_reuse = (
        settings["use_cache"]
        and minute_path.exists()
        and hour_path.exists()
    )
    if can_reuse:
        minute_rows = load_ohlcv(str(minute_path))
        hour_rows = load_ohlcv(str(hour_path))
        notes.append(
            f"Loaded cache: {minute_path.name} ({len(minute_rows)}) · "
            f"{hour_path.name} ({len(hour_rows)})"
        )
        # If cache is shorter than requested window, still allow but warn.
        expected = expected_1m_candles(days)
        if len(minute_rows) + 60 < expected:
            notes.append(
                f"Cache has {len(minute_rows)} 1m bars; requested ~{expected}. "
                "Uncheck cache and re-run to fetch more."
            )
        return minute_rows, hour_rows, " | ".join(notes)

    history_url = _history_base_url(settings["base_url"])
    client = DeltaExchangeClient(base_url=history_url)
    hour_rows = client.fetch_historical_ohlcv(
        symbol=symbol, resolution="1h", days=hour_days
    )
    minute_rows = client.fetch_historical_ohlcv(
        symbol=symbol, resolution="1m", days=days
    )
    minute_rows = trim_ohlcv_to_days(minute_rows, days, "1m")
    save_ohlcv(hour_rows, str(hour_path))
    save_ohlcv(minute_rows, str(minute_path))
    notes.append(
        f"Fetched from {history_url}: 1h={len(hour_rows)} · 1m={len(minute_rows)}"
    )
    return minute_rows, hour_rows, " | ".join(notes)


def run_backtest(settings: dict[str, Any]) -> dict[str, Any]:
    minute_rows, hour_rows, data_note = _load_or_fetch_ohlcv(settings)
    rule = build_strategy_rule(
        instrument=settings["symbol"],
        starting_wallet_usd=settings["starting_wallet_usd"],
        swing_strength=settings["swing_strength"],
        confirmation_timeout_bars=settings["confirmation_timeout_bars"],
        take_profit_points=settings["take_profit_points"],
        trailing_stop_points=settings["trailing_stop_points"],
        position_lots=settings["position_lots"],
        partial_exit_lots=settings["partial_exit_lots"],
        runner_lots=settings["runner_lots"],
        fee_pct_per_side=settings["fee_pct_per_side"],
    )

    events: list[dict[str, Any]] = []

    def on_event(name: str, payload: dict[str, Any]) -> None:
        if not settings["show_debug"]:
            return
        if name in {
            "levels_locked",
            "liquidity_sweep",
            "first_confirmation_candle",
            "setup_rejected",
            "partial_taken",
            "trade_entered",
            "trade_closed",
            "confirmation_reset",
            "reset_levels",
        }:
            events.append({"event": name, "payload": payload})

    result = backtest_1h_liquidity_reversal(
        minute_rows,
        hour_rows,
        rule,
        debug=False,
        on_event=on_event if settings["show_debug"] else None,
    )

    ensure_data_dirs()
    out_json = REPORTS_DIR / "1h_liquidity_reversal_results.json"
    out_events = REPORTS_DIR / "1h_liquidity_reversal_events.json"
    out_json.write_text(json.dumps(result_to_dict(result), indent=2), encoding="utf-8")
    out_events.write_text(json.dumps(events, indent=2, default=str), encoding="utf-8")

    return {
        "result": result,
        "rule": rule,
        "minute_rows": minute_rows,
        "hour_rows": hour_rows,
        "events": events,
        "data_note": data_note,
        "results_path": str(out_json),
        "events_path": str(out_events),
        "settings": settings,
    }


def render_overview_metrics(bundle: dict[str, Any]) -> None:
    result: BacktestResult = bundle["result"]
    settings = bundle["settings"]
    totals = _trades_totals(result, settings["starting_wallet_usd"])

    st.subheader("Backtest results")
    st.caption(bundle["data_note"])

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Trades", result.total_trades)
    m2.metric("Win rate", f"{result.win_rate}%")
    m3.metric("Strategy return", f"{result.total_return_pct}%")
    m4.metric("Buy & hold", f"{result.buy_hold_return_pct}%")
    m5.metric("Max drawdown", f"{result.max_drawdown_pct}%")
    m6.metric("Verdict", result.verdict)

    st.markdown(_verdict_badge(result.verdict))

    p1, p2, p3, p4 = st.columns(4)
    p1.metric("Net P/L", _format_usd(totals["net_usd"]))
    p2.metric("Final wallet", _format_usd(totals["final_wallet"]))
    p3.metric("Wins / Losses", f"{totals['wins']} / {totals['losses']}")
    p4.metric("Total points", totals["total_points"])

    c1, c2, c3 = st.columns(3)
    c1.metric("1m candles", len(bundle["minute_rows"]))
    c2.metric("1h candles", len(bundle["hour_rows"]))
    c3.metric("Debug events", len(bundle["events"]))

    if result.rule_compliance:
        with st.expander("Rule compliance", expanded=False):
            for key, value in result.rule_compliance.items():
                if isinstance(value, bool):
                    st.write(f"{'✅' if value else '❌'} {key.replace('_', ' ')}")
                elif key not in {"last_setup"}:
                    st.write(f"• **{key.replace('_', ' ')}:** `{value}`")


def render_charts(bundle: dict[str, Any]) -> None:
    result: BacktestResult = bundle["result"]
    st.subheader("Charts")
    if not result.trades:
        st.info("No trades to chart.")
        return

    st.markdown(render_win_loss_summary(result), unsafe_allow_html=True)
    st.markdown(render_cumulative_pnl_chart(result), unsafe_allow_html=True)
    st.markdown(render_trade_pnl_bars(result), unsafe_allow_html=True)
    st.markdown(
        render_trades_on_price(bundle["minute_rows"], result),
        unsafe_allow_html=True,
    )
    st.caption(
        "Blue ≈ entry · green/red ≈ exit. Price chart uses 1m closes in the backtest window."
    )


def render_trades(bundle: dict[str, Any]) -> None:
    result: BacktestResult = bundle["result"]
    settings = bundle["settings"]
    st.subheader("Trade log")
    if not result.trades:
        st.write("No trades generated for this window.")
        return

    totals = _trades_totals(result, settings["starting_wallet_usd"])
    rows = _trades_table(result)
    rows.append(
        {
            "Trade": "TOTAL",
            "Entry": "",
            "Exit": "",
            "Entry Price": "",
            "Exit Price": "",
            "Lots": "",
            "Points": totals["total_points"],
            "P/L ($)": _format_usd(totals["net_usd"]),
            "Return %": "",
            "Wallet": _format_usd(totals["final_wallet"]),
            "Exit Reason": "",
        }
    )
    st.dataframe(rows, use_container_width=True)


def _event_summary_rows(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in events:
        name = item.get("event", "")
        payload = item.get("payload") or {}
        setup = payload.get("setup") if isinstance(payload.get("setup"), dict) else payload
        if not isinstance(setup, dict):
            setup = {}
        rows.append(
            {
                "Event": name,
                "Direction": setup.get("trade_direction") or setup.get("sweep_direction") or "",
                "Swing High": setup.get("1h_swing_high", ""),
                "Swing Low": setup.get("1h_swing_low", ""),
                "Sweep": setup.get("sweep_direction", ""),
                "Sweep TS": setup.get("sweep_ts", ""),
                "Entry": setup.get("entry_price", payload.get("entry", "")),
                "SL": setup.get("stop_loss", ""),
                "TP": setup.get("take_profit", ""),
                "Reason": payload.get("reason", ""),
            }
        )
    return rows


def render_debug_events(bundle: dict[str, Any]) -> None:
    st.subheader("Setup / debug events")
    events = bundle["events"]
    if not events:
        st.info("No debug events captured. Enable **Capture debug events** and re-run.")
        return

    filter_opts = sorted({e.get("event", "") for e in events})
    selected = st.multiselect(
        "Filter events",
        options=filter_opts,
        default=[
            e
            for e in [
                "levels_locked",
                "liquidity_sweep",
                "partial_taken",
                "setup_rejected",
                "trade_entered",
                "trade_closed",
            ]
            if e in filter_opts
        ],
        key="lr1h_event_filter",
    )
    filtered = [e for e in events if not selected or e.get("event") in selected]
    st.dataframe(_event_summary_rows(filtered), use_container_width=True)

    with st.expander("Raw event JSON", expanded=False):
        st.json(filtered[-50:])


def render_downloads(bundle: dict[str, Any]) -> None:
    st.subheader("Downloads")
    result: BacktestResult = bundle["result"]
    events = bundle["events"]
    st.download_button(
        "Download results JSON",
        data=json.dumps(result_to_dict(result), indent=2),
        file_name="1h_liquidity_reversal_results.json",
        mime="application/json",
        key="lr1h_dl_results",
    )
    st.download_button(
        "Download debug events JSON",
        data=json.dumps(events, indent=2, default=str),
        file_name="1h_liquidity_reversal_events.json",
        mime="application/json",
        key="lr1h_dl_events",
    )
    st.download_button(
        "Download strategy rules JSON",
        data=json.dumps(asdict(bundle["rule"]), indent=2),
        file_name="1h_liquidity_reversal_rules.json",
        mime="application/json",
        key="lr1h_dl_rules",
    )
    st.caption(f"Also saved under `{bundle['results_path']}`")


def render_liquidity_reversal_app() -> None:
    """Full Streamlit page for strategy details + backtesting."""
    st.title("1H Liquidity Reversal")
    st.caption(
        "Standalone ETH strategy — 1H swing liquidity sweep + 1m two-candle reversal. "
        "Independent from the YouTube / LQDTY strategy."
    )

    settings = render_sidebar_settings()

    tab_details, tab_backtest = st.tabs(["Strategy Details", "Backtest"])

    with tab_details:
        rule = build_strategy_rule(
            instrument=settings["symbol"],
            starting_wallet_usd=settings["starting_wallet_usd"],
            swing_strength=settings["swing_strength"],
            confirmation_timeout_bars=settings["confirmation_timeout_bars"],
            take_profit_points=settings["take_profit_points"],
            trailing_stop_points=settings["trailing_stop_points"],
            position_lots=settings["position_lots"],
            partial_exit_lots=settings["partial_exit_lots"],
            runner_lots=settings["runner_lots"],
            fee_pct_per_side=settings["fee_pct_per_side"],
        )
        render_strategy_details()
        st.divider()
        render_rules_panel(rule)

    with tab_backtest:
        if settings["run"]:
            try:
                with st.spinner(
                    f"Running {STRATEGY_NAME} on {settings['symbol']} "
                    f"({settings['days']}d)..."
                ):
                    bundle = run_backtest(settings)
                st.session_state["lr1h_bundle"] = bundle
                st.success("Backtest complete.")
            except Exception as exc:  # noqa: BLE001
                st.error(f"Backtest failed: {exc}")
                return

        bundle = st.session_state.get("lr1h_bundle")
        if bundle is None:
            st.info(
                "Configure parameters in the sidebar and click **Run Backtest**. "
                "Cached OHLCV under `data/ohlcv/` is reused when available."
            )
            st.markdown(
                """
                ### What the backtest does
                1. Load / fetch ETH **1h** and **1m** candles from Delta Exchange
                2. Lock confirmed 1H swing high / low (no look-ahead)
                3. Wait for liquidity sweep → 1m two-candle confirmation
                4. Simulate entries with fixed TP and first-candle wick SL
                5. Show metrics, charts, trades, and debug events
                """
            )
            return

        (
            tab_overview,
            tab_charts,
            tab_trades,
            tab_events,
            tab_rules,
            tab_files,
        ) = st.tabs(
            ["Overview", "Charts", "Trades", "Debug Events", "Rules Used", "Downloads"]
        )
        with tab_overview:
            render_overview_metrics(bundle)
        with tab_charts:
            render_charts(bundle)
        with tab_trades:
            render_trades(bundle)
        with tab_events:
            render_debug_events(bundle)
        with tab_rules:
            render_rules_panel(bundle["rule"])
        with tab_files:
            render_downloads(bundle)

    st.caption("_For research only. Past performance does not guarantee future results._")
