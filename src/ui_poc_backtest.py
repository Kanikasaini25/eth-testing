"""Streamlit UI for the 15-minute previous-day POC backtest."""

from __future__ import annotations

import streamlit as st

from src.config import DELTA_BACKTEST_BASE_URL
from src.delta_data import DeltaExchangeClient
from src.live_poc_strategy import default_poc_rules_path, load_poc_rule
from src.poc_backtest import PocBacktestParams, params_from_rule, run_poc_backtest
from src.rule_extractor import TradingRule

POC_CANDLE_API_URL = DELTA_BACKTEST_BASE_URL

TRADE_COLUMNS = (
    ("side", "side"),
    ("entry_ts", "entry"),
    ("exit_ts", "exit"),
    ("entry_price", "entry px"),
    ("exit_price", "exit px"),
    ("stop_loss", "stop"),
    ("target", "target"),
    ("entry_line", "level"),
    ("lots", "lots"),
    ("lot_usd", "$ / point"),
    ("size_usd", "size USD"),
    ("risk_usd", "risk USD"),
    ("points", "points"),
    ("profit", "profit pts"),
    ("loss", "loss pts"),
    ("fee_usd", "fees"),
    ("net_usd", "Net P/L"),
    ("reason", "reason"),
)


def _collect_poc_params(defaults: PocBacktestParams) -> tuple[int, PocBacktestParams]:
    col_a, col_b, col_c = st.columns(3)
    with col_a:
        days = st.select_slider(
            "Lookback days",
            options=[7, 14, 21, 30, 60, 90, 180, 365, 730, 1095, 1460],
            value=365,
            key="poc_days",
        )
    with col_b:
        wallet = st.number_input(
            "Starting wallet (USD)",
            min_value=100.0,
            value=float(defaults.starting_wallet_usd),
            step=100.0,
            key="poc_wallet",
        )
    with col_c:
        lots = st.number_input(
            "Max lots",
            min_value=1,
            value=defaults.position_lots,
            step=1,
            key="poc_lots",
        )
    st.caption("365 = 1 year. 3–4 years can take several minutes to download 15m candles.")

    with st.expander("15m filters (defaults from strategy JSON)", expanded=False):
        f1, f2, f3 = st.columns(3)
        with f1:
            risk_pct = st.number_input(
                "Risk per trade (%)",
                min_value=0.1,
                value=float(defaults.risk_pct_per_trade),
                step=0.1,
                format="%.1f",
                key="poc_risk_pct",
            )
            target = st.number_input(
                "Min take profit (points)",
                min_value=1.0,
                value=float(defaults.target_points),
                step=1.0,
                key="poc_target",
            )
            away = st.number_input(
                "Must first leave POC by (points)",
                min_value=0.0,
                value=float(defaults.min_away_points),
                step=1.0,
                key="poc_away",
            )
            sweep = st.number_input(
                "Min wick through POC (points)",
                min_value=0.0,
                value=float(defaults.min_sweep_points),
                step=0.5,
                key="poc_sweep",
            )
            bin_size = st.number_input(
                "Volume profile bin size",
                min_value=0.1,
                value=float(defaults.bin_size),
                step=0.1,
                format="%.1f",
                key="poc_bin",
            )
        with f2:
            min_sl = st.number_input(
                "Min stop (points)",
                min_value=0.0,
                value=float(defaults.min_sl_points),
                step=0.5,
                key="poc_min_sl",
            )
            max_sl = st.number_input(
                "Max stop (points)",
                min_value=0.0,
                value=float(defaults.max_sl_points),
                step=0.5,
                key="poc_max_sl",
            )
            min_rr = st.number_input(
                "Min reward:risk",
                min_value=0.0,
                value=float(defaults.min_reward_to_risk),
                step=0.1,
                format="%.1f",
                key="poc_min_rr",
            )
            reward_r = st.number_input(
                "Reward multiple (R)",
                min_value=0.0,
                value=float(defaults.reward_r_multiple),
                step=0.5,
                format="%.1f",
                key="poc_reward_r",
            )
            max_range = st.number_input(
                "Skip if today already moved (points)",
                min_value=0.0,
                value=float(defaults.max_intraday_range),
                step=10.0,
                key="poc_max_range",
            )
        with f3:
            daily_loss = st.number_input(
                "Max daily loss (%)",
                min_value=0.0,
                value=float(defaults.daily_loss_pct),
                step=0.5,
                format="%.1f",
                key="poc_daily_loss",
            )
            max_day = st.number_input(
                "Max trades per day",
                min_value=0,
                value=int(defaults.max_trades_per_day),
                step=1,
                key="poc_max_day",
            )
            leverage = st.number_input(
                "Max leverage",
                min_value=1.0,
                max_value=5.0,
                value=float(defaults.max_leverage),
                step=0.5,
                format="%.1f",
                key="poc_leverage",
            )
            fee = st.number_input(
                "Fee per side (%)",
                min_value=0.0,
                value=float(defaults.fee_pct_per_side),
                step=0.01,
                format="%.3f",
                key="poc_fee",
            )
        c1, c2, c3 = st.columns(3)
        with c1:
            use_htf = st.checkbox(
                "Require previous-day direction",
                value=defaults.use_htf_bias,
                key="poc_htf",
            )
            require_return = st.checkbox(
                "Wait for return to POC",
                value=defaults.require_return,
                key="poc_return",
            )
            require_pullback = st.checkbox(
                "Only fade pullbacks vs day open",
                value=defaults.require_open_pullback,
                key="poc_pullback",
            )
        with c2:
            skip_monday = st.checkbox("Skip Mondays", value=defaults.skip_monday, key="poc_monday")
            use_session = st.checkbox(
                "Trade only 08:00–20:00 UTC",
                value=defaults.use_session_filter,
                key="poc_session",
            )
            use_be = st.checkbox(
                "Move stop to breakeven at 1.5R",
                value=defaults.move_stop_to_breakeven,
                key="poc_be",
            )
        with c3:
            trade_poc = st.checkbox("Trade POC", value=defaults.trade_poc, key="poc_trade_poc")
            trade_val = st.checkbox("Trade VAL", value=defaults.trade_val, key="poc_trade_val")
            trade_vah = st.checkbox("Trade VAH", value=defaults.trade_vah, key="poc_trade_vah")

    params = PocBacktestParams(
        target_points=float(target),
        position_lots=int(lots),
        fee_pct_per_side=float(fee),
        starting_wallet_usd=float(wallet),
        usd_per_point_per_lot=float(defaults.usd_per_point_per_lot),
        min_sl_points=float(min_sl),
        max_sl_points=float(max_sl),
        min_reward_to_risk=float(min_rr),
        reward_r_multiple=float(reward_r),
        use_session_filter=bool(use_session),
        session_start_hour_utc=defaults.session_start_hour_utc,
        session_end_hour_utc=defaults.session_end_hour_utc,
        max_trades_per_day=int(max_day),
        use_htf_bias=bool(use_htf),
        use_risk_sizing=defaults.use_risk_sizing,
        risk_pct_per_trade=float(risk_pct),
        min_lots=defaults.min_lots,
        daily_loss_pct=float(daily_loss),
        max_leverage=float(leverage),
        move_stop_to_breakeven=bool(use_be),
        breakeven_r_multiple=float(defaults.breakeven_r_multiple),
        warmup_days=float(defaults.warmup_days),
        bin_size=float(bin_size),
        value_area_pct=defaults.value_area_pct,
        touch_points=float(defaults.touch_points),
        trade_poc=bool(trade_poc),
        trade_val=bool(trade_val),
        trade_vah=bool(trade_vah),
        require_return=bool(require_return),
        require_open_pullback=bool(require_pullback),
        max_intraday_range=float(max_range),
        skip_monday=bool(skip_monday),
        min_away_points=float(away),
        min_sweep_points=float(sweep),
        min_close_beyond=float(defaults.min_close_beyond),
        min_body_points=float(defaults.min_body_points),
    )
    return int(days), params


def _render_metrics(result) -> None:
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
    col9, col10, col11 = st.columns(3)
    col9.metric("Total fees", f"{result.total_fees:,.2f}")
    col10.metric("Avg win (pts)", f"{result.avg_win_points:,.2f}")
    col11.metric("Avg loss (pts)", f"{result.avg_loss_points:,.2f}")


def _render_equity_curve(equity: list[dict]) -> None:
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
    svg = (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="240" '
        f'style="background:#0e1117;border-radius:8px;">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
        f'points="{" ".join(points)}" />'
        f'<text x="{pad}" y="18" fill="#9ca3af" font-size="12">{high:,.2f}</text>'
        f'<text x="{pad}" y="{height - 6}" fill="#9ca3af" font-size="12">{low:,.2f}</text>'
        f"</svg>"
    )
    st.markdown(svg, unsafe_allow_html=True)


def _cell(value, *, column: str = "") -> str:
    if isinstance(value, float):
        if column in {"size_usd", "risk_usd", "fee_usd", "net_usd", "lot_usd"}:
            text = f"{value:,.2f}"
        else:
            text = f"{value:.2f}"
        if column == "net_usd":
            color = "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#9ca3af"
            return f"<span style='color:{color};font-weight:600'>{text}</span>"
        return text
    return str(value)


def _render_trades(trades: list[dict]) -> None:
    rows_data = []
    for trade in trades:
        points = float(trade.get("points") or 0.0)
        lots = float(trade.get("lots") or 0.0)
        entry = float(trade.get("entry_price") or 0.0)
        stop = float(trade.get("stop_loss") or 0.0)
        row = dict(trade)
        row["profit"] = points if points > 0 else 0.0
        row["loss"] = points if points < 0 else 0.0
        row["lot_usd"] = float(row.get("lot_usd") or lots)
        row["size_usd"] = float(row.get("size_usd") or (lots * entry))
        row["risk_usd"] = float(row.get("risk_usd") or (lots * abs(entry - stop)))
        rows_data.append(row)
    total_points = sum(float(row["points"]) for row in rows_data)
    total_profit = sum(float(row["profit"]) for row in rows_data)
    total_loss = sum(float(row["loss"]) for row in rows_data)
    total_fees = sum(float(row.get("fee_usd") or 0.0) for row in rows_data)
    total_net = sum(float(row.get("net_usd") or 0.0) for row in rows_data)
    total_size = sum(float(row.get("size_usd") or 0.0) for row in rows_data)
    total_risk = sum(float(row.get("risk_usd") or 0.0) for row in rows_data)
    headers = "".join(
        f"<th style='text-align:left;padding:6px'>{label}</th>" for _, label in TRADE_COLUMNS
    )
    rows = []
    for row in rows_data:
        cells = "".join(
            f"<td style='padding:6px'>{_cell(row.get(key, ''), column=key)}</td>"
            for key, _ in TRADE_COLUMNS
        )
        rows.append(f"<tr>{cells}</tr>")
    totals = {
        "side": "TOTAL",
        "points": total_points,
        "profit": total_profit,
        "loss": total_loss,
        "fee_usd": total_fees,
        "net_usd": total_net,
        "size_usd": total_size,
        "risk_usd": total_risk,
    }
    total_cells = "".join(
        f"<td style='padding:6px'><b>{_cell(totals.get(key, ''), column=key)}</b></td>"
        for key, _ in TRADE_COLUMNS
    )
    st.markdown(
        "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr style='border-top:2px solid #9ca3af'>{total_cells}</tr></tfoot></table></div>",
        unsafe_allow_html=True,
    )
    st.caption(
        f"Profit: {total_profit:+.2f} pts · Loss: {total_loss:+.2f} pts · "
        f"Fees: {total_fees:,.2f} USD · Net P/L: {total_net:+,.2f} USD."
    )


def _render_poc_rules(rule: TradingRule) -> None:
    with st.expander("15m strategy rules", expanded=False):
        st.markdown(f"**{rule.name}**")
        for section in ("setup_rules", "entry_rules", "exit_rules", "risk_rules"):
            items = getattr(rule, section)
            if not items:
                continue
            st.markdown(f"*{section.replace('_', ' ').title()}*")
            for item in items:
                st.markdown(f"- {item}")


def render_poc_backtest_page(symbol: str, _base_url: str = "") -> None:
    st.subheader("15-Minute Previous-Day POC Backtest")
    st.caption(
        "Previous-day volume profile on 15m, then wait for price to leave POC and reject back. "
        "Candles come from **India live** (`api.india.delta.exchange`), same as the new-stg2 branch — "
        "not the demo/testnet feed."
    )
    rules_path = default_poc_rules_path()
    if not rules_path.exists():
        st.warning(f"15m rules not found: `{rules_path}`")
        return

    rule = load_poc_rule(rules_path)
    st.caption(f"Rules: `{rules_path.name}`")
    _render_poc_rules(rule)
    days, params = _collect_poc_params(params_from_rule(rule.parameters))
    run = st.button("Run 15m backtest", type="primary", key="run_poc_backtest")

    if run:
        try:
            status = st.empty()
            fetch_days = int(days + max(params.warmup_days, 1))
            status.info(f"Fetching 15m candles ({fetch_days} days including previous session)…")
            client = DeltaExchangeClient(base_url=POC_CANDLE_API_URL)
            m15_rows = client.fetch_historical_ohlcv(
                symbol=symbol, resolution="15m", days=fetch_days
            )
            status.info("Simulating previous-day volume profile trades…")
            result = run_poc_backtest(m15_rows, params)
            status.empty()
        except Exception as exc:  # noqa: BLE001
            st.error(f"15m backtest failed: {exc}")
            return
        st.session_state["poc_backtest_result"] = result
        st.session_state["poc_backtest_meta"] = (
            len(m15_rows),
            symbol,
            days,
            params.warmup_days,
        )

    stored = st.session_state.get("poc_backtest_result")
    meta = st.session_state.get("poc_backtest_meta")
    if stored is None or meta is None:
        st.info("Click **Run 15m backtest** to test the POC strategy on its own.")
        return

    m15_count, used_symbol, used_days, used_warmup = meta
    st.success(f"Last 15m run: {used_symbol}, last {used_days} day(s)")
    st.caption(
        f"Trades from the last {used_days} day(s). Loaded {used_warmup:g} extra day(s) "
        f"for previous-day volume profile ({m15_count} 15m candles)."
    )
    _render_metrics(stored)
    st.subheader("Equity curve")
    _render_equity_curve(stored.equity)
    st.subheader("Trades")
    if stored.trades:
        _render_trades(stored.trades)
    else:
        st.write("No 15m POC return-and-reject setups in this window. Try a longer lookback.")
