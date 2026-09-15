from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestParams, run_liquidity_backtest
from src.config import get_env, get_market_data_base_url, get_trade_base_url
from src.delta_data import fetch_closed_ohlcv
from src.delta_trading import trade_network_label
from src.presets import STATS, STRATEGY, SUMMARY
from src.timezone import (
    IST_LABEL,
    ist_day_end_epoch,
    ist_day_start_epoch,
    ist_display,
    today_ist,
)

WARMUP_DAYS = 2


def load_ohlcv(symbol: str, resolution: str, start: int, end: int, status) -> list[dict]:
    data_url = get_market_data_base_url()

    def on_progress(fetched: float, total: int, res: str) -> None:
        status.info(
            f"Fetching India-live {res} candles from {data_url} "
            f"({fetched:.1f}/{total:.0f} days, same feed as live demo)…"
        )

    return fetch_closed_ohlcv(
        symbol=symbol,
        resolution=resolution,
        on_progress=on_progress,
        base_url=data_url,
        start=start,
        end=end,
    )


def date_range_picker() -> tuple[date, date]:
    st.sidebar.header("Backtest window")
    today = today_ist()
    default_start = today - timedelta(days=180)
    start = st.sidebar.date_input(
        "Start date (IST)", value=default_start, max_value=today, format="YYYY-MM-DD"
    )
    end = st.sidebar.date_input(
        "End date (IST)", value=today, max_value=today, format="YYYY-MM-DD"
    )
    span = (end - start).days + 1
    if end < start:
        st.sidebar.error("End date must be on or after the start date.")
    else:
        st.sidebar.caption(
            f"{span} day(s) of India-live 1-minute candles. "
            "Long windows take a few minutes to download."
        )
    return start, end


def sidebar_params() -> tuple[str, date, date, BacktestParams]:
    tuned = STRATEGY

    st.sidebar.header("Market data")
    st.sidebar.markdown("**India live** — same candles as the live demo runner")
    st.sidebar.caption(f"{get_market_data_base_url()} · times shown in {IST_LABEL}")
    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD"))

    start_date, end_date = date_range_picker()

    st.sidebar.header("Position")
    lots = st.sidebar.number_input("Trade size (lots)", min_value=1, value=100, step=1)

    st.sidebar.header("Strategy rules")
    st.sidebar.caption("Pre-filled from the tuned strategy. Change anything to test a variant.")
    target = st.sidebar.number_input(
        "Take profit (points)", min_value=1.0, value=tuned.target_points, step=1.0
    )
    left = st.sidebar.number_input("Swing left bars", min_value=1, value=tuned.swing_left, step=1)
    right = st.sidebar.number_input("Swing right bars", min_value=1, value=tuned.swing_right, step=1)
    lookback = st.sidebar.number_input(
        "Swing lookback (15m bars)", min_value=5, value=tuned.swing_lookback, step=1
    )
    timeout = st.sidebar.number_input(
        "Confirm timeout (minutes)", min_value=5, value=tuned.confirm_timeout_minutes, step=5
    )
    sl_buffer = st.sidebar.number_input(
        "Stop buffer (points)", min_value=0.0, value=tuned.sl_buffer_points, step=0.5
    )
    max_sl = st.sidebar.number_input(
        "Max stop (points)", min_value=0.0, value=tuned.max_sl_points, step=1.0
    )
    min_sweep = st.sidebar.number_input(
        "Min grab through swing (points)", min_value=0.0, value=tuned.min_sweep_points, step=0.5
    )
    min_body = st.sidebar.number_input(
        "Min 1m confirm body (points)", min_value=0.0, value=tuned.min_confirm_body, step=0.5
    )
    use_sl = st.sidebar.checkbox(
        "Use stop at liquidity-grab extreme", value=tuned.use_stop_loss
    )
    require_reclaim = st.sidebar.checkbox(
        "Require reclaim of the 15m swing", value=tuned.require_reclaim
    )
    close_back = st.sidebar.checkbox(
        "15m must wick through and close back", value=tuned.require_close_back
    )
    close_break = st.sidebar.checkbox(
        "Second 1m must close beyond the first", value=tuned.require_close_break
    )
    one_shot = st.sidebar.checkbox(
        "Only the first two 1m candles after the grab", value=tuned.one_shot_confirm
    )
    use_partial = st.sidebar.checkbox(
        "Scale out at take profit and let the rest run", value=tuned.partial_exit_pct > 0
    )
    scale_pct = st.sidebar.number_input(
        "Scale-out size (% of position)",
        min_value=10.0,
        max_value=90.0,
        value=tuned.partial_exit_pct if tuned.partial_exit_pct > 0 else 50.0,
        step=10.0,
    )
    runner_tp = st.sidebar.number_input(
        "Runner take profit (points, 0 = let the rest run to breakeven/stop)",
        min_value=0.0,
        value=tuned.runner_target_points,
        step=10.0,
    )
    max_hold = st.sidebar.number_input(
        "Force exit after (minutes, 0 = off)",
        min_value=0.0,
        value=tuned.max_hold_minutes,
        step=5.0,
        help=(
            "Closing inside the scalper window waives the exchange's closing fee. "
            "Measured on 180 days: a 29-minute cap cuts fees 22% but cuts gross profit "
            "more, so it ends up worse. Off by default."
        ),
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
    slippage = st.sidebar.number_input(
        "Slippage per trade (points)", min_value=0.0, value=0.0, step=0.5
    )
    st.sidebar.caption(
        "Delta India ETHUSD: taker 0.05%, maker 0.02%. "
        "Join the Scalper Offer on the ETHUSD page first — it waives the closing "
        "fee when a fill closes within 30 minutes. "
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
        slippage_points=float(slippage),
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
        partial_exit_pct=float(scale_pct) if use_partial else 0.0,
        runner_target_points=float(runner_tp),
        max_hold_minutes=float(max_hold),
    )
    return symbol.strip().upper(), start_date, end_date, params


def setup_stats(trades: list[dict]) -> tuple[int, float, float]:
    """Collapse scale-out fills into one round trip so the win rate isn't double counted."""
    nets: dict[tuple, float] = {}
    for trade in trades:
        key = (trade["entry_ts"], trade["side"])
        nets[key] = nets.get(key, 0.0) + float(trade.get("net_usd") or 0.0)
    values = list(nets.values())
    if not values:
        return 0, 0.0, 0.0
    wins = [value for value in values if value > 0]
    return len(values), len(wins) / len(values), sum(values) / len(values)


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
    holds = [float(t.get("hold_minutes") or 0.0) for t in result.trades]
    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Avg hold (min)", f"{sum(holds) / len(holds):,.0f}" if holds else "0")
    col10.metric("Avg win (pts)", f"{result.avg_win_points:,.2f}")
    col11.metric("Avg loss (pts)", f"{result.avg_loss_points:,.2f}")
    col12.metric("Liquidity grabs", str(result.grab_count))
    setups, setup_win, setup_expectancy = setup_stats(result.trades)
    if setups:
        st.caption(
            f"**Per round trip** (scale-out and runner counted as one trade): "
            f"{setups} trades · {setup_win * 100:.1f}% win rate · "
            f"${setup_expectancy:,.2f} average per trade. "
            "The tiles above count each fill separately."
        )
    scalped = sum(1 for trade in result.trades if trade.get("scalper_applied"))
    if scalped:
        st.caption(
            f"Scalper offer waived the close fee on {scalped} of {result.trade_count} fills "
            "(exit within 30 minutes)."
        )


def render_fees(trades: list[dict], params: BacktestParams) -> None:
    """Fees are the biggest controllable drag, so show exactly where they go."""
    if not trades:
        return
    gross = sum(float(t.get("gross_usd") or 0.0) for t in trades)
    entry_fee = sum(float(t.get("fee_entry_usd") or 0.0) for t in trades)
    exit_fee = sum(float(t.get("fee_exit_usd") or 0.0) for t in trades)
    total_fee = entry_fee + exit_fee
    waived = sum(1 for t in trades if t.get("scalper_applied"))
    net = gross - total_fee

    st.subheader("Fees")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Gross P/L", f"${gross:,.2f}")
    col2.metric("Total fees", f"${total_fee:,.2f}", f"-{total_fee / gross * 100:.0f}% of gross"
                if gross > 0 else None)
    col3.metric("Net P/L", f"${net:,.2f}")
    col4.metric("Fee per fill", f"${total_fee / len(trades):,.2f}")

    entry_share = entry_fee / total_fee * 100 if total_fee else 0.0
    st.caption(
        f"**Entry ${entry_fee:,.2f}** ({entry_share:.0f}% of fees) · "
        f"**Exit ${exit_fee:,.2f}** ({100 - entry_share:.0f}%). "
        f"The scalper offer waived the closing fee on **{waived} of {len(trades)}** fills "
        f"({waived / len(trades) * 100:.0f}%) that closed within "
        f"{params.scalper_minutes:g} minutes."
    )
    tips = []
    if not params.maker_on_take_profit:
        tips.append(
            "Turn on **maker fee on take-profit limits** — a resting reduce-only limit pays "
            f"{params.fee_maker_pct:g}% instead of {params.fee_pct_per_side:g}%."
        )
    if not params.scalper_offer:
        tips.append(
            "Join the **Scalper Offer** on the Delta ETHUSD page. It waives the closing fee "
            "entirely on trades that exit within 30 minutes."
        )
    if params.partial_exit_pct > 0:
        tips.append(
            "Scaling out doubles the number of exit fills, so it roughly doubles exit fees. "
            "The tuned strategy exits in one fill for that reason."
        )
    if waived / len(trades) < 0.6:
        tips.append(
            f"Only {waived / len(trades) * 100:.0f}% of exits land inside the scalper window. "
            "Raising the exit rate here is the single largest remaining fee saving, but a "
            "forced time exit was measured as a net loss — it cuts winners short."
        )
    tips.append(
        "Entry is always taker on a breakout: a buy limit at the break level crosses the ask. "
        "Only a pullback-style entry could earn the maker rebate, at the cost of missed fills."
    )
    with st.expander("How to reduce these fees"):
        st.markdown("\n".join(f"- {tip}" for tip in tips))


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


TIME_COLUMNS = {"grab_ts", "entry_ts", "exit_ts"}

TRADE_COLUMNS = (
    ("side", "side"),
    ("grab_ts", "liq grab (IST)"),
    ("entry_ts", "entry (IST)"),
    ("exit_ts", "exit (IST)"),
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
    if column in TIME_COLUMNS and value:
        return ist_display(str(value))
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
        "Delta ETHUSD: 1 lot = 0.01 ETH ($0.01 per point). All times are IST."
    )


def render_rules(params: BacktestParams) -> None:
    scale = int(params.partial_exit_pct)
    scaled_lots = params.position_lots * scale // 100
    runner_lots = params.position_lots - scaled_lots
    exit_rule = (
        f"- **Exit:** take **{scaled_lots} lots** off at +{params.target_points:g} points, "
        f"move the remaining **{runner_lots} lots** to breakeven and run them to "
        f"+{params.runner_target_points:g}."
        if scale
        else f"- **Exit:** close the whole position at +{params.target_points:g} points."
    )
    with st.expander("Strategy rules (from the current settings)"):
        st.markdown(
            f"""
- Mark 15-minute swing highs and lows (fractal, {params.swing_left} bars left /
  {params.swing_right} right), looking back {params.swing_lookback} bars.
- **Downside grab:** a 15-minute candle wicks at least {params.min_sweep_points:g} points below a
  swing low{" and closes back above it" if params.require_close_back else ""}.
- **Upside grab:** a 15-minute candle wicks at least {params.min_sweep_points:g} points above a
  swing high{" and closes back below it" if params.require_close_back else ""}.
- **Entry:** two consecutive 1-minute reversal candles with bodies of at least
  {params.min_confirm_body:g} points; enter when the second breaks the first. Size
  {params.position_lots} lots. The setup expires after
  {params.confirm_timeout_minutes} minutes.
{exit_rule}
- Stop sits {params.sl_buffer_points:g} points beyond the grab extreme. Skip the trade if that
  would be wider than {params.max_sl_points:g} points.
            """
        )


def run_backtest(symbol: str, start_date: date, end_date: date, params: BacktestParams):
    status = st.empty()
    start = ist_day_start_epoch(start_date)
    end = ist_day_end_epoch(end_date)
    # 15m bars start earlier so swings are already marked when the window opens
    warmup = start - WARMUP_DAYS * 86400
    m15_rows = load_ohlcv(symbol, "15m", warmup, end, status)
    m1_rows = load_ohlcv(symbol, "1m", start, end, status)
    status.info("Simulating 15-minute liquidity grabs with 1-minute confirmation…")
    result = run_liquidity_backtest(m15_rows, m1_rows, params)
    status.empty()
    return result, m15_rows, m1_rows


def main() -> None:
    st.set_page_config(page_title="15m Liquidity Grab + 1m Confirmation", layout="wide")
    st.title("15-Minute Liquidity Grab + 1-Minute Confirmation")
    data_url = get_market_data_base_url()
    trade_url = get_trade_base_url()
    st.write(
        "Backtest and live demo both read **India live** ETHUSD candles (no cache, closed bars "
        "only). A 15-minute candle wicks through a swing, then two 1-minute reversal candles "
        "confirm the entry. The sidebar is pre-filled with the tuned strategy; override any "
        "rule to test a variant."
    )
    st.caption(
        f"Market data: **India live** `{data_url}` · "
        f"Orders stay on **{trade_network_label(trade_url)}** `{trade_url}` · "
        f"All timestamps in **{IST_LABEL}**"
    )
    st.caption(
        f"{SUMMARY} Measured over 180 days at 100 lots: **{STATS.setups} trades**, "
        f"**{STATS.win_rate * 100:.1f}% win rate**, **${STATS.net_pnl:,.0f} net** "
        f"(${STATS.gross_pnl:,.0f} gross less ${STATS.total_fees:,.0f} fees), "
        f"**${STATS.max_drawdown:,.0f} max drawdown**, PF {STATS.profit_factor:.2f}, "
        f"profitable in {STATS.folds_profitable}/{STATS.folds} folds."
    )

    symbol, start_date, end_date, params = sidebar_params()
    render_rules(params)
    if st.sidebar.button("Run backtest", type="primary"):
        if end_date < start_date:
            st.error("End date must be on or after the start date.")
            return
        try:
            result, m15_rows, m1_rows = run_backtest(symbol, start_date, end_date, params)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["liq_result"] = result
        st.session_state["liq_params"] = params
        st.session_state["liq_meta"] = (
            len(m15_rows),
            len(m1_rows),
            symbol,
            f"{start_date} to {end_date}",
            get_market_data_base_url(),
        )

    stored = st.session_state.get("liq_result")
    meta = st.session_state.get("liq_meta")
    used_params = st.session_state.get("liq_params", params)
    if stored is None or meta is None:
        return
    m15_count, m1_count, used_symbol, used_window, used_feed = meta
    st.success(
        f"Last run: {used_symbol} on India live `{used_feed}` · **{used_window}** IST · "
        f"{m15_count} closed 15m · {m1_count} closed 1m · {stored.swing_count} swings"
    )
    render_metrics(stored)
    render_fees(stored.trades, used_params)
    st.subheader("Equity curve")
    render_equity_curve(stored.equity)
    st.subheader("Trades")
    if stored.trades:
        render_trades(stored.trades)
    else:
        st.write("No two-candle confirmation fills in this window. Try a wider date range.")


if __name__ == "__main__":
    main()
