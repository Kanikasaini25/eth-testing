from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestParams, bar_seconds_for_resolution, run_pattern_backtest
from src.config import get_candle_base_url, get_env, reload_env
from src.delta_data import DeltaExchangeClient
from src.product_specs import backtest_params_from_env, lots_for_one_usd_per_point, fetch_product_specs
from src.symbols import DELTA_TRADEABLE, resolve_delta_symbol

# Streamlit keeps one process alive — re-read .env every script run.
reload_env(override=True)
CANDLE_API_URL = get_candle_base_url()
WARMUP_DAYS = 2

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


def load_ohlcv(
    symbol: str,
    resolution: str,
    start_date: date,
    end_date: date,
    status,
) -> list[dict]:
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    start_ts, end_ts = _day_bounds(start_date, end_date)

    def on_progress(fetched: float, total: float, res: str) -> None:
        status.info(
            f"Fetching live {res} candles from Delta India LIVE ({fetched:.1f}/{total:.1f} days, no cache)…"
        )

    return client.fetch_historical_ohlcv_range(
        symbol=symbol,
        resolution=resolution,
        start=start_ts,
        end=end_ts,
        on_progress=on_progress,
    )


def sidebar_params() -> tuple[str, date, date, str, BacktestParams]:
    st.sidebar.header("Backtest settings")
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
        "Longer ranges can take several minutes to download from India Delta LIVE."
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
    return symbol, start_date, end_date, candle_resolution, params


def render_metrics(result) -> None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Net PnL (USD)", f"${result.net_pnl:,.2f}")
    col2.metric("Gross P/L (USD)", f"${sum(float(t.get('gross_usd', 0)) for t in result.trades):,.2f}" if result.trades else "$0.00")
    col3.metric("Win rate", f"{result.win_rate * 100:.1f}%")
    col4.metric("Trades", str(result.trade_count))
    col5, col6, col7, col8 = st.columns(4)
    col5.metric("Take profits", str(result.tp_count))
    col6.metric("Stop losses", str(result.sl_count))
    col7.metric("Profit factor", f"{result.profit_factor:.2f}")
    col8.metric("Max drawdown (USD)", f"${result.max_drawdown:,.2f}")
    col9, col10, col11, col12 = st.columns(4)
    col9.metric("Total fees (USD)", f"${result.total_fees:,.2f}")
    col10.metric("Avg win (pts)", f"{result.avg_win_points:,.2f}")
    col11.metric("Avg loss (pts)", f"{result.avg_loss_points:,.2f}")
    col12.metric("Patterns found", str(result.grab_count))
    scalped = sum(1 for trade in result.trades if trade.get("scalper_applied"))
    if scalped:
        st.caption(
            f"Scalper offer waived the close fee on {scalped} of {result.trade_count} fills "
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
    st.caption(
        f"Fees: ${total_fees:,.2f} USD · Net P/L: ${total_net:+,.2f} USD. "
        "Delta India products are quoted, settled, and margined in **USD** (not INR). "
        "Gold on Delta is **PAXGUSD/XAUTUSD** (not classic XAUUSD). "
        f"Scale out T1–T5: **{get_env('EXIT_SCALE_PCTS', '20,30,20,15')} / rest**. "
        "After T3, SL=T3 (for T4); after T4, SL=T4 (for T5)."
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
        be = get_env("BREAKEVEN_POINTS", "18")
    else:
        step = float(params.target_points)
        scale = list(params.exit_scale_pcts)[:4]
        while len(scale) < 4:
            scale.append(10.0)
        lots = int(params.position_lots)
        votes = str(params.min_overlay_votes)
        max_sl = f"{params.max_sl_points:.0f}"
        rr = str(params.min_rr_ratio)
        be = f"{params.breakeven_points:.0f}"
    s1, s2, s3, s4 = (f"{float(x):.0f}%" for x in scale[:4])
    with st.expander("Strategy rules · gold overlays · USD take-profits", expanded=True):
        st.markdown(
            f"""
### Data & currency
- Candles: **India Delta LIVE · PAXGUSD** · all P&L / prices in **USD**.
- Active size: **{lots} lots** (~${lots / 1000:.1f} per $1 move).

### Entry — classic Hammer / Shooting Star
- **BUY:** strict Hammer → 1m green close above high · **SL = hammer low**
- **SELL:** strict Shooting Star → 1m red close below low · **SL = star high**
- Filters: ≥**{votes}/5** overlays · max SL **{max_sl}** · min R:R **{rr}** · BE +**{be}**

### Take profit ladder (from entry, USD) — % of **original** size
| Level | Price (BUY) | Book | Stop after fill |
|-------|-------------|------|-----------------|
| **T1** | entry + 1×step | **{s1}** | SL → mid(entry, T1) |
| **T2** | entry + 2×step | **{s2}** | SL → T1 |
| **T3** | entry + 3×step | **{s3}** | SL → **T3** |
| **T4** | entry + 4×step | **{s4}** | SL → **T4** |
| **T5** | entry + 5×step | **all remaining** | close all |

So while targeting **T4**, SL is **T3**; while targeting **T5**, SL is **T4**.  
Default step floor ≈ **{step:.0f}** USD (or ATR / risk adaptive).
            """
        )


def run_backtest(
    symbol: str,
    start_date: date,
    end_date: date,
    candle_resolution: str,
    params: BacktestParams,
):
    if start_date > end_date:
        raise ValueError("Select date must be on or before End date.")

    status = st.empty()
    fetch_start = start_date - timedelta(days=WARMUP_DAYS)
    signal_rows = load_ohlcv(symbol, candle_resolution, fetch_start, end_date, status)
    m1_rows = load_ohlcv(symbol, "1m", fetch_start, end_date, status)
    status.info(
        "Simulating Hammer/Star + gold overlays (EMA/ADX/Donchian, BB+RSI, ATR, sessions)…"
    )
    result = run_pattern_backtest(
        signal_rows,
        m1_rows,
        params,
        bar_seconds=bar_seconds_for_resolution(candle_resolution),
    )
    status.empty()
    return result, signal_rows, m1_rows, candle_resolution


def main() -> None:
    st.set_page_config(page_title="Hammer & Shooting Star Backtest", layout="wide")
    st.title("Hammer & Shooting Star Pattern Backtest")
    st.write(
        "Data: **India Delta LIVE** · Currency: **USD only**. "
        "Entry: **Hammer / Shooting Star** + gold overlays "
        "(EMA/ADX/Donchian · Bollinger+RSI · ATR stops · London/NY sessions). "
        "Gold = **PAXGUSD**."
    )
    symbol, start_date, end_date, candle_resolution, params = sidebar_params()
    render_rules(params)
    st.sidebar.info(
        f"Loaded from `.env`: **{params.position_lots} lots** · T={params.target_points:.0f} · "
        f"votes≥{params.min_overlay_votes} · scale={list(params.exit_scale_pcts)} · "
        f"maxSL={params.max_sl_points:.0f} · BE={params.breakeven_points:.0f}"
    )
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, signal_rows, m1_rows, used_candle = run_backtest(
                symbol, start_date, end_date, candle_resolution, params
            )
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["liq_result"] = result
        st.session_state["liq_meta"] = (
            len(signal_rows),
            len(m1_rows),
            symbol,
            start_date,
            end_date,
            used_candle,
        )
        st.session_state["liq_params_snapshot"] = {
            "lots": params.position_lots,
            "target": params.target_points,
            "votes": params.min_overlay_votes,
            "scale": list(params.exit_scale_pcts),
        }

    stored = st.session_state.get("liq_result")
    meta = st.session_state.get("liq_meta")
    if stored is None or meta is None:
        return
    signal_count, m1_count, used_symbol, used_start, used_end, used_candle = meta
    st.success(
        f"Last run: {used_symbol} · India Delta LIVE · USD · {used_start} → {used_end} · "
        f"{used_candle} · {signal_count} signal bars · {m1_count} 1m · "
        f"{stored.grab_count} patterns"
    )
    render_metrics(stored)
    st.subheader("Equity curve")
    render_equity_curve(stored.equity)
    st.subheader("Trades")
    if stored.trades:
        render_trades(stored.trades)
    else:
        st.write("No Hammer or Shooting Star confirmation fills in this window. Try a longer lookback.")


if __name__ == "__main__":
    main()
