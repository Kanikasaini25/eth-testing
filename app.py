from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import (
    BacktestParams,
    bar_seconds_for_resolution,
    filter_trades_by_entry_window,
    run_pattern_backtest,
)
from src.config import INDIA_LIVE_URL, TESTNET_INDIA_URL, get_env, reload_env
from src.delta_data import DeltaExchangeClient, closed_ohlcv, sanitize_ohlcv
from src.product_specs import backtest_params_from_env, lots_for_one_usd_per_point, fetch_product_specs
from src.symbols import DELTA_TRADEABLE, resolve_delta_symbol
from src.swings import epoch_of

# Streamlit keeps one process alive — re-read .env every script run.
reload_env(override=True)
WARMUP_DAYS = 2

DATA_SOURCE_OPTIONS: dict[str, str] = {
    "india_live": "India LIVE — production market backtest",
    "testnet_match": "Testnet — match live fills (same as demo orders)",
}


def _default_data_mode() -> int:
    order_url = get_env("DELTA_BASE_URL", INDIA_LIVE_URL).lower()
    return 1 if "testnet" in order_url else 0
# Keep simulating open runners after end_date so T1/runner can fill like live.
RUNNER_EXIT_BUFFER_DAYS = 7


def _simulation_end_date(end_date: date) -> date:
    """1m exit sim cannot use future dates — cap at today."""
    buffered = end_date + timedelta(days=RUNNER_EXIT_BUFFER_DAYS)
    return min(buffered, date.today())

CANDLE_OPTIONS: dict[str, str] = {
    "5 min": "5m",
    "15": "15m",
    "30": "30m",
    "60": "1h",
    "45": "45m",
    "1 days": "1d",
    "1 week": "1w",
}

SYMBOL_LABELS: dict[str, str] = {
    "ETHUSD": "ETHUSD (ETH perpetual)",
    "PAXGUSD": "PAXGUSD (PAX Gold ≈ XAU)",
    "XAUTUSD": "XAUTUSD (Tether Gold)",
    "BTCUSD": "BTCUSD (BTC perpetual)",
}


def _day_bounds(start: date, end: date) -> tuple[int, int]:
    start_ts = int(datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    end_ts = int(
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc).timestamp()
        - 1
    )
    return start_ts, end_ts


def _runner_gap_notes(
    trades: list[dict], m1_rows: list[dict], *, source_label: str = "India LIVE"
) -> list[str]:
    """Explain runner_end_of_data vs candle price path."""
    notes: list[str] = []
    for trade in trades:
        if trade.get("reason") != "runner_end_of_data":
            continue
        entry_ts = epoch_of(trade["entry_ts"])
        entry = float(trade["entry_price"])
        side = str(trade["side"])
        target = float(trade.get("target") or 0.0)
        if not target:
            runner_pts = float(get_env("RUNNER_TARGET_POINTS", "200") or "200")
            target = entry + runner_pts if side == "long" else entry - runner_pts
        post = [row for row in m1_rows if epoch_of(row["timestamp"]) >= entry_ts]
        if not post:
            continue
        if side == "long":
            extreme = max(float(row["high"]) for row in post)
            gap = target - extreme
            notes.append(
                f"Runner TP **${target:,.2f}** not reached on **{source_label}** candles "
                f"(high after entry **${extreme:,.2f}**, **{gap:.1f}** pts short). "
                "Switch to **Testnet — match live fills** mode to align with demo orders."
            )
        else:
            extreme = min(float(row["low"]) for row in post)
            gap = extreme - target
            notes.append(
                f"Runner TP **${target:,.2f}** not reached on **{source_label}** candles "
                f"(low after entry **${extreme:,.2f}**, **{gap:.1f}** pts short). "
                "Switch to **Testnet — match live fills** mode to align with demo orders."
            )
    return notes


def load_ohlcv(
    symbol: str,
    resolution: str,
    start_date: date,
    end_date: date,
    status,
    *,
    candle_base_url: str,
    source_label: str,
) -> list[dict]:
    client = DeltaExchangeClient(base_url=candle_base_url)
    start_ts, end_ts = _day_bounds(start_date, end_date)

    def on_progress(fetched: float, total: float, res: str) -> None:
        status.info(
            f"Fetching {res} candles from **{source_label}** "
            f"({fetched:.1f}/{total:.1f} days, no cache)…"
        )

    return client.fetch_historical_ohlcv_range(
        symbol=symbol,
        resolution=resolution,
        start=start_ts,
        end=end_ts,
        on_progress=on_progress,
    )


def sidebar_params() -> tuple[str, date, date, str, BacktestParams, str]:
    st.sidebar.header("Backtest settings")
    data_mode = st.sidebar.radio(
        "Data source",
        options=list(DATA_SOURCE_OPTIONS.keys()),
        format_func=lambda key: DATA_SOURCE_OPTIONS[key],
        index=_default_data_mode(),
        help=(
            "**India LIVE** = production candles only. "
            "**Testnet match** = India entries + testnet 1m exits (matches demo fills)."
        ),
    )
    if data_mode == "india_live":
        st.sidebar.caption(f"Candles: `{INDIA_LIVE_URL}`")
    else:
        st.sidebar.caption(
            f"Entries: `{INDIA_LIVE_URL}` · Exits: `{TESTNET_INDIA_URL}` (sanitized 1m)"
        )
    env_symbol, env_notice = resolve_delta_symbol(get_env("DELTA_SYMBOL", "ETHUSD"))
    symbol_options = [s for s in DELTA_TRADEABLE if s in SYMBOL_LABELS]
    default_idx = symbol_options.index(env_symbol) if env_symbol in symbol_options else 0
    symbol = st.sidebar.selectbox(
        "Symbol (Delta India LIVE)",
        options=symbol_options,
        index=default_idx,
        format_func=lambda s: SYMBOL_LABELS.get(s, s),
    )
    st.sidebar.caption(
        "Delta does **not** list classic XAUUSD. Gold on Delta = **PAXGUSD** (default) / **XAUTUSD** "
        "(live production candles, not testnet). True XAUUSD CFD → MT5/PDMBulls."
    )
    if env_notice and env_symbol == symbol:
        st.sidebar.info(env_notice)
    days = st.sidebar.select_slider(
        "Lookback days",
        options=[3, 7, 14, 21, 30, 45, 60, 90, 180, 200, 365],
        value=30,
    )
    st.sidebar.caption(
        "Longer ranges can take several minutes to download."
        if data_mode == "india_live"
        else "Testnet mode uses India LIVE signals + testnet 1m for exit prices."
    )
    start_date = st.sidebar.date_input("Select date", value=date.today() - timedelta(days=int(days)))
    end_date = st.sidebar.date_input("End date", value=date.today())
    candle_label = st.sidebar.selectbox(
        "Candle option",
        options=list(CANDLE_OPTIONS.keys()),
        index=1,
    )
    candle_resolution = CANDLE_OPTIONS[candle_label]
    params = backtest_params_from_env(symbol)
    specs = fetch_product_specs(symbol)
    one_dollar_lots = lots_for_one_usd_per_point(specs, usd_per_point=1.0)
    default_lots = int(params.position_lots)
    lot_options = sorted(
        set(
            [
                100,
                250,
                500,
                750,
                1000,
                1500,
                2000,
                2500,
                2800,
                3000,
                4000,
                5000,
                one_dollar_lots,
                default_lots,
            ]
        )
    )
    # Key includes default so changing POSITION_LOTS in .env resets the slider.
    lots = st.sidebar.select_slider(
        "Trade size (lots)",
        options=lot_options,
        value=default_lots if default_lots in lot_options else one_dollar_lots,
        key=f"lots_{symbol}_{default_lots}",
    )
    usd_per_point = lots * params.usd_per_point_per_lot
    st.sidebar.caption(
        f"**${usd_per_point:.2f} USD profit per $1 price move** · "
        f"{one_dollar_lots} lots = **$1 / $1** on {symbol} "
        f"(1 lot = ${params.usd_per_point_per_lot:.4f}/pt)"
    )
    if params.use_live_exits:
        t1_pct = params.partial_exit_pct / 100.0
        st.sidebar.caption(
            f"**Live exits:** T1 (+{params.target_points:.0f}) books {params.partial_exit_pct:.0f}% ≈ "
            f"${usd_per_point * params.target_points * t1_pct:.0f} USD · "
            f"runner +{params.runner_target_points:.0f} @ BE"
        )
    else:
        scale = list(params.exit_scale_pcts) if params.exit_scale_pcts else [30.0]
        t1_pct = float(scale[0]) / 100.0
        scale_txt = "/".join(f"{float(x):.0f}" for x in scale) + "/rest"
        st.sidebar.caption(
            f"T1 (+{params.target_points:.0f}) books {scale[0]:.0f}% ≈ "
            f"${usd_per_point * params.target_points * t1_pct:.0f} USD · "
            f"scale {scale_txt} · T4 SL=T3 · T5 SL=T4"
        )
    params.position_lots = int(lots)
    st.sidebar.caption(
        f"{symbol} · USD · Hammer/Star + gold overlays "
        f"(≥{params.min_overlay_votes}/5 overlays · max SL {params.max_sl_points:.0f} · "
        f"R:R {params.min_rr_ratio} · BE +{params.breakeven_points:.0f})"
    )
    return symbol, start_date, end_date, candle_resolution, params, data_mode


def _metrics_from_trades(trades: list[dict], result) -> dict:
    if not trades:
        return {
            "net_pnl": 0.0,
            "gross": 0.0,
            "fees": 0.0,
            "win_rate": 0.0,
            "trade_count": 0,
            "wins": 0,
            "losses": 0,
            "tp_count": 0,
            "sl_count": 0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
            "avg_win_points": 0.0,
            "avg_loss_points": 0.0,
        }
    wins = [t for t in trades if float(t.get("net_usd") or 0) > 0]
    losses = [t for t in trades if float(t.get("net_usd") or 0) <= 0]
    win_gross = sum(float(t.get("net_usd") or 0) for t in wins)
    loss_gross = abs(sum(float(t.get("net_usd") or 0) for t in losses))
    pf = win_gross / loss_gross if loss_gross else (999.0 if win_gross else 0.0)
    tp = sum(1 for t in trades if str(t.get("reason", "")).startswith(("take_profit", "runner_take")))
    sl = sum(1 for t in trades if "stop_loss" in str(t.get("reason", "")))
    return {
        "net_pnl": sum(float(t.get("net_usd") or 0) for t in trades),
        "gross": sum(float(t.get("gross_usd") or 0) for t in trades),
        "fees": sum(float(t.get("fee_usd") or 0) for t in trades),
        "win_rate": len(wins) / len(trades),
        "trade_count": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "tp_count": tp,
        "sl_count": sl,
        "profit_factor": pf,
        "max_drawdown": result.max_drawdown,
        "avg_win_points": (
            sum(float(t.get("points") or 0) for t in wins) / len(wins) if wins else 0.0
        ),
        "avg_loss_points": (
            sum(float(t.get("points") or 0) for t in losses) / len(losses) if losses else 0.0
        ),
    }


def render_metrics(result, window_trades: list[dict] | None = None) -> None:
    trades = window_trades if window_trades is not None else result.trades
    stats = _metrics_from_trades(trades, result)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL (USD)", f"${stats['net_pnl']:,.2f}")
    col2.metric("Gross P/L (USD)", f"${stats['gross']:,.2f}")
    col3.metric("Win rate", f"{stats['win_rate'] * 100:.1f}%")
    col4.metric("Fills in window", str(stats["trade_count"]))
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Take profits", str(stats["tp_count"]))
    col6.metric("Stop losses", str(stats["sl_count"]))
    col7.metric("Profit factor", f"{stats['profit_factor']:.2f}")
    col8.metric("Max drawdown (USD)", f"${stats['max_drawdown']:,.2f}")
    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Total fees (USD)", f"${stats['fees']:,.2f}")
    col10.metric("Avg win (pts)", f"{stats['avg_win_points']:,.2f}")
    col11.metric("Avg loss (pts)", f"{stats['avg_loss_points']:,.2f}")
    col12.metric("Patterns found", str(result.grab_count))
    scalped = sum(1 for trade in trades if trade.get("scalper_applied"))
    if scalped:
        st.caption(
            f"Scalper offer waived the close fee on {scalped} of {len(trades)} fills "
            "(exit within 30 minutes)."
        )


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
    st.caption("Equity curve · wallet balance in **USD** (India Delta LIVE prices)")
    st.html(
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="240" '
        f'style="background:#0e1117;border-radius:8px;">'
        f'<text x="{pad}" y="18" fill="#9ca3af" font-size="12">USD ${high:,.2f}</text>'
        f'<text x="{pad}" y="{height - 6}" fill="#9ca3af" font-size="12">USD ${low:,.2f}</text>'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
        f'points="{" ".join(points)}" />'
        f"</svg>"
    )


TRADE_COLUMNS = (
    ("side", "side"),
    ("grab_ts", "pattern"),
    ("entry_ts", "entry"),
    ("exit_ts", "exit"),
    ("entry_price", "entry USD"),
    ("exit_price", "exit USD"),
    ("stop_loss", "stop USD"),
    ("target", "target USD"),
    ("swing_price", "pattern level USD"),
    ("lots", "lots"),
    ("points", "points"),
    ("fee_usd", "fees USD"),
    ("net_usd", "Net P/L USD"),
    ("reason", "reason"),
)


def _cell(value, *, column: str = "") -> str:
    money_cols = {"fee_usd", "net_usd"}
    price_cols = {"entry_price", "exit_price", "stop_loss", "target", "swing_price"}
    if isinstance(value, float):
        if column in money_cols:
            text = f"${value:,.2f}"
            if column == "net_usd":
                color = "#16a34a" if value > 0 else "#dc2626" if value < 0 else "#9ca3af"
                return f"<span style='color:{color};font-weight:600'>{text}</span>"
            return text
        if column in price_cols:
            return f"${value:,.2f}"
        return f"{value:.2f}"
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
    exit_note = (
        f"Live exits: **{get_env('PARTIAL_EXIT_PCT', '45')}% @ T1 (+{get_env('TARGET_POINTS', '28')})**, "
        f"runner +{get_env('RUNNER_TARGET_POINTS', '200')} @ BE."
        if get_env("USE_LIVE_EXITS", "true").lower() in {"1", "true", "yes", "on"}
        else f"Scale out T1–T5: **{get_env('EXIT_SCALE_PCTS', '20,30,20,15')} / rest**."
    )
    st.caption(
        f"Fees: ${total_fees:,.2f} USD · Net P/L: ${total_net:+,.2f} USD. "
        "Delta India products are quoted, settled, and margined in **USD** (not INR). "
        "Gold on Delta is **PAXGUSD/XAUTUSD** (not classic XAUUSD). "
        f"{exit_note}"
    )


def render_rules(params: BacktestParams | None = None) -> None:
    if params is None:
        step = float(get_env("TARGET_POINTS", "30") or "30")
        scale = [float(x) for x in (get_env("EXIT_SCALE_PCTS", "20,30,20,15") or "20,30,20,15").split(",")[:4]]
        while len(scale) < 4:
            scale.append(10.0)
        lots = int(get_env("POSITION_LOTS", "3000") or "3000")
        votes = get_env("MIN_OVERLAY_VOTES", "3")
        max_sl = get_env("MAX_SL_POINTS", "18")
        rr = get_env("MIN_RR_RATIO", "2.0")
        live_exits = get_env("USE_LIVE_EXITS", "true").lower() in {"1", "true", "yes", "on"}
        partial = float(get_env("PARTIAL_EXIT_PCT", "45") or "45")
        runner = float(get_env("RUNNER_TARGET_POINTS", "200") or "200")
    else:
        step = float(params.target_points)
        scale = list(params.exit_scale_pcts)[:4]
        while len(scale) < 4:
            scale.append(10.0)
        lots = int(params.position_lots)
        votes = str(params.min_overlay_votes)
        max_sl = f"{params.max_sl_points:.0f}"
        rr = str(params.min_rr_ratio)
        live_exits = params.use_live_exits
        partial = params.partial_exit_pct
        runner = params.runner_target_points
    s1, s2, s3, s4 = (f"{float(x):.0f}%" for x in scale[:4])
    with st.expander("Strategy rules · gold overlays · USD take-profits", expanded=True):
        exit_block = (
            f"""
### Exits — same as live runner (`run_live.py`)
- **T1:** limit **{partial:.0f}%** of size @ entry ± **{step:.0f}** USD
- **Runner:** remaining size · stop → **breakeven** · TP @ entry ± **{runner:.0f}** USD
- Full-position stop until T1 fills (no early BE trail)
            """
            if live_exits
            else f"""
### Take profit ladder (from entry, USD) — % of **original** size
| Level | Price (BUY) | Book | Stop after fill |
|-------|-------------|------|-----------------|
| **T1** | entry + 1×step | **{s1}** | SL → mid(entry, T1) |
| **T2** | entry + 2×step | **{s2}** | SL → T1 |
| **T3** | entry + 3×step | **{s3}** | SL → **T3** |
| **T4** | entry + 4×step | **{s4}** | SL → **T4** |
| **T5** | entry + 5×step | **all remaining** | close all |

So while targeting **T4**, SL is **T3**; while targeting **T5**, SL is **T4**.
            """
        )
        st.markdown(
            f"""
### Data & currency
- Candles: **India Delta LIVE · PAXGUSD** · all P&L / prices in **USD**.
- Active size: **{lots} lots** (~${lots * 0.001:.2f} per $1 move on gold).

### Entry — classic Hammer / Shooting Star
- **BUY:** strict Hammer → 1m green close above high · **SL = hammer low**
- **SELL:** strict Shooting Star → 1m red close below low · **SL = star high**
- Filters: ≥**{votes}/5** overlays · max SL **{max_sl}** · min R:R **{rr}**
{exit_block}
            """
        )


def run_backtest(
    symbol: str,
    start_date: date,
    end_date: date,
    candle_resolution: str,
    params: BacktestParams,
    *,
    match_testnet: bool = False,
):
    if start_date > end_date:
        raise ValueError("Select date must be on or before End date.")

    status = st.empty()
    fetch_start = start_date - timedelta(days=WARMUP_DAYS)
    m1_end = _simulation_end_date(end_date)
    signal_rows = load_ohlcv(
        symbol,
        candle_resolution,
        fetch_start,
        end_date,
        status,
        candle_base_url=INDIA_LIVE_URL,
        source_label="India LIVE",
    )
    m1_rows = load_ohlcv(
        symbol,
        "1m",
        fetch_start,
        m1_end,
        status,
        candle_base_url=INDIA_LIVE_URL,
        source_label="India LIVE",
    )
    m1_exit_rows: list[dict] | None = None
    if match_testnet:
        status.info("Fetching testnet 1m candles for exit simulation (spike-filtered)…")
        raw_exit = load_ohlcv(
            symbol,
            "1m",
            fetch_start,
            m1_end,
            status,
            candle_base_url=TESTNET_INDIA_URL,
            source_label="Testnet",
        )
        m1_exit_rows = sanitize_ohlcv(closed_ohlcv(raw_exit, "1m"))
    buffer_note = (
        f"through **{m1_end}** ({RUNNER_EXIT_BUFFER_DAYS}d past end date)"
        if m1_end > end_date
        else f"through **{m1_end}** (today — cannot fetch future candles)"
    )
    status.info(
        "Simulating Hammer/Star + live exits (T1 partial + runner). "
        + (
            "Entries on **India LIVE** · exits on **testnet 1m**. "
            if match_testnet
            else ""
        )
        + f"1m exit sim runs {buffer_note}…"
    )
    result = run_pattern_backtest(
        signal_rows,
        closed_ohlcv(m1_rows, "1m"),
        params,
        bar_seconds=bar_seconds_for_resolution(candle_resolution),
        m1_exit_rows=m1_exit_rows,
    )
    status.empty()
    return result, signal_rows, m1_rows, candle_resolution, match_testnet


def main() -> None:
    st.set_page_config(page_title="Hammer & Shooting Star Backtest", layout="wide")
    st.title("Hammer & Shooting Star Pattern Backtest")
    symbol, start_date, end_date, candle_resolution, params, data_mode = sidebar_params()
    if data_mode == "india_live":
        st.write(
            "Mode: **India LIVE candle backtest** · Currency: **USD only**. "
            "Entry: **Hammer / Shooting Star** + gold overlays. Gold = **PAXGUSD**."
        )
    else:
        st.write(
            "Mode: **Testnet — match live fills** · Strategy entries on **India LIVE** candles, "
            "exit simulation on **testnet 1m** (same price feed as your demo orders). "
            f"Orders: `{get_env('DELTA_BASE_URL', TESTNET_INDIA_URL)}`."
        )
    render_rules(params)
    order_src = get_env("DELTA_BASE_URL", TESTNET_INDIA_URL)
    st.sidebar.info(
        f"Loaded from `.env`: **{params.position_lots} lots** · T={params.target_points:.0f} · "
        f"votes≥{params.min_overlay_votes} · "
        + (
            f"live exits {params.partial_exit_pct:.0f}%/+{params.runner_target_points:.0f}"
            if params.use_live_exits
            else f"scale={list(params.exit_scale_pcts)} · BE={params.breakeven_points:.0f}"
        )
        + f" · maxSL={params.max_sl_points:.0f}"
    )
    if data_mode == "india_live":
        st.sidebar.caption(f"Candles: `{INDIA_LIVE_URL}` · Orders: `{order_src}`")
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, signal_rows, m1_rows, used_candle, matched = run_backtest(
                symbol,
                start_date,
                end_date,
                candle_resolution,
                params,
                match_testnet=(data_mode == "testnet_match"),
            )
            start_ts, end_ts = _day_bounds(start_date, end_date)
            window_trades = filter_trades_by_entry_window(
                result.trades, start_epoch=start_ts, end_epoch=end_ts
            )
            st.session_state["liq_data_mode"] = data_mode
            st.session_state["liq_result"] = result
            st.session_state["liq_meta"] = (
                len(signal_rows),
                len(m1_rows),
                symbol,
                start_date,
                end_date,
                used_candle,
            )
            if data_mode == "testnet_match":
                st.session_state["liq_runner_notes"] = []
            else:
                st.session_state["liq_runner_notes"] = _runner_gap_notes(
                    window_trades, m1_rows, source_label="India LIVE"
                )
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return

    active_mode = st.session_state.get("liq_data_mode")
    meta = st.session_state.get("liq_meta")
    if meta is None:
        return

    signal_count, m1_count, used_symbol, used_start, used_end, used_candle = meta
    start_ts, end_ts = _day_bounds(used_start, used_end)

    stored = st.session_state.get("liq_result")
    if stored is None:
        return
    window_trades = filter_trades_by_entry_window(
        stored.trades, start_epoch=start_ts, end_epoch=end_ts
    )
    if active_mode == "testnet_match":
        st.success(
            f"Testnet-aligned backtest: {used_symbol} · entries `{INDIA_LIVE_URL}` · "
            f"exits `{TESTNET_INDIA_URL}` · **{used_start} → {used_end}** · "
            f"{used_candle} · {signal_count} signal bars · {m1_count} 1m · "
            f"{stored.grab_count} patterns · **{len(window_trades)} fills** in window"
        )
    else:
        st.success(
            f"India LIVE backtest: {used_symbol} · `{INDIA_LIVE_URL}` · USD · "
            f"entries **{used_start} → {used_end}** · "
            f"{used_candle} · {signal_count} signal bars · {m1_count} 1m · "
            f"{stored.grab_count} patterns · **{len(window_trades)} fills** in window"
        )
    render_metrics(stored, window_trades)
    for note in st.session_state.get("liq_runner_notes") or []:
        st.warning(note)
    st.subheader("Equity curve")
    render_equity_curve(stored.equity)
    st.subheader("Trades")
    if window_trades:
        render_trades(window_trades)
    else:
        st.write("No Hammer or Shooting Star confirmation fills in this window. Try a longer lookback.")


if __name__ == "__main__":
    main()
