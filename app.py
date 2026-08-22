from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestParams, params_from_rule, run_m15_backtest
from src.config import STRATEGIES_DIR, get_env
from src.delta_data import DeltaExchangeClient
from src.rule_extractor import rules_from_json

RULES_PATH = STRATEGIES_DIR / "wI9b968AvW8_rules.json"
CANDLE_API_URL = "https://api.india.delta.exchange"


def load_rule():
    rules = rules_from_json(RULES_PATH.read_text(encoding="utf-8"))
    if not rules:
        raise FileNotFoundError(f"No strategy rules in {RULES_PATH}")
    return rules[0]


@st.cache_data(ttl=300, show_spinner=False)
def load_ohlcv(symbol: str, resolution: str, days: int) -> list[dict]:
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    return client.fetch_historical_ohlcv(symbol=symbol, resolution=resolution, days=days)


def sidebar_params(defaults: BacktestParams) -> tuple[str, int, BacktestParams]:
    st.sidebar.header("Backtest settings")
    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD"))
    days = st.sidebar.select_slider(
        "Lookback days",
        options=[1, 3, 7, 14, 21, 30, 60, 90, 180],
        value=7,
    )
    st.sidebar.caption(
        "Each run also loads 7 extra days first so swings and trend match. "
        "Those extra days are not counted as trades. "
        "60+ day windows take longer to download."
    )
    lots = st.sidebar.number_input("Max lots", min_value=1, value=defaults.position_lots, step=1)
    risk_pct = st.sidebar.number_input(
        "Risk per trade (%)",
        min_value=0.1,
        value=float(defaults.risk_pct_per_trade),
        step=0.1,
        format="%.1f",
    )
    daily_loss = st.sidebar.number_input(
        "Max daily loss (%)",
        min_value=0.0,
        value=float(defaults.daily_loss_pct),
        step=0.5,
        format="%.1f",
    )
    target = st.sidebar.number_input(
        "Take profit (points)",
        min_value=1.0,
        value=float(defaults.target_points),
        step=1.0,
    )
    fractal = st.sidebar.slider(
        "Swing fractal bars",
        min_value=1,
        max_value=5,
        value=defaults.swing_fractal_bars,
    )
    window = st.sidebar.slider(
        "Confirmation window (1m bars)",
        min_value=5,
        max_value=60,
        value=defaults.confirmation_window_bars,
    )
    min_sl = st.sidebar.number_input(
        "Min stop (points)",
        min_value=0.0,
        value=float(defaults.min_sl_points),
        step=0.5,
    )
    max_sl = st.sidebar.number_input(
        "Max stop (points)",
        min_value=0.0,
        value=float(defaults.max_sl_points),
        step=0.5,
    )
    min_rr = st.sidebar.number_input(
        "Min reward:risk",
        min_value=0.0,
        value=float(defaults.min_reward_to_risk),
        step=0.1,
        format="%.1f",
    )
    require_close = st.sidebar.checkbox(
        "Second candle must close beyond first",
        value=defaults.require_close_beyond,
    )
    use_session = st.sidebar.checkbox(
        "Trade only 08:00–20:00 UTC",
        value=defaults.use_session_filter,
    )
    use_trend = st.sidebar.checkbox(
        "Only trade with 15m trend (no shorts in uptrend)",
        value=defaults.use_trend_filter,
    )
    use_be = st.sidebar.checkbox(
        "Move stop to breakeven at 1R",
        value=defaults.move_stop_to_breakeven,
    )
    trend_lookback = st.sidebar.slider(
        "Trend lookback (15m bars)",
        min_value=8,
        max_value=48,
        value=int(defaults.trend_lookback_bars),
    )
    min_sweep = st.sidebar.number_input(
        "Min sweep (points)",
        min_value=0.0,
        value=float(defaults.min_sweep_points),
        step=0.5,
    )
    reward_r = st.sidebar.number_input(
        "Reward multiple (R)",
        min_value=0.0,
        value=float(defaults.reward_r_multiple),
        step=0.5,
        format="%.1f",
    )
    max_day = st.sidebar.number_input(
        "Max trades per day",
        min_value=0,
        value=int(defaults.max_trades_per_day),
        step=1,
    )
    wallet = st.sidebar.number_input(
        "Starting wallet (USD)",
        min_value=100.0,
        value=float(defaults.starting_wallet_usd),
        step=100.0,
    )
    fee = st.sidebar.number_input(
        "Fee per side (%)",
        min_value=0.0,
        value=float(defaults.fee_pct_per_side),
        step=0.01,
        format="%.3f",
    )
    params = BacktestParams(
        target_points=float(target),
        position_lots=int(lots),
        swing_fractal_bars=int(fractal),
        confirmation_window_bars=int(window),
        fee_pct_per_side=float(fee),
        starting_wallet_usd=float(wallet),
        require_close_beyond=bool(require_close),
        min_sl_points=float(min_sl),
        max_sl_points=float(max_sl),
        min_reward_to_risk=float(min_rr),
        stop_loss_mode=defaults.stop_loss_mode,
        min_sweep_points=float(min_sweep),
        reward_r_multiple=float(reward_r),
        use_session_filter=bool(use_session),
        session_start_hour_utc=defaults.session_start_hour_utc,
        session_end_hour_utc=defaults.session_end_hour_utc,
        max_trades_per_day=int(max_day),
        use_trend_filter=bool(use_trend),
        trend_lookback_bars=int(trend_lookback),
        use_risk_sizing=True,
        risk_pct_per_trade=float(risk_pct),
        daily_loss_pct=float(daily_loss),
        move_stop_to_breakeven=bool(use_be),
        warmup_days=float(defaults.warmup_days),
    )
    return symbol.strip().upper(), int(days), params


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
    col9, col10, col11 = st.columns(3)
    col9.metric("Total fees", f"{result.total_fees:,.2f}")
    col10.metric("Avg win (pts)", f"{result.avg_win_points:,.2f}")
    col11.metric("Avg loss (pts)", f"{result.avg_loss_points:,.2f}")
    if result.net_points > 0 and result.net_pnl < 0:
        st.warning(
            "Price points were positive but fees turned the result negative. "
            "Fewer, higher-quality trades usually help more than a larger take-profit."
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
    st.html(
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="240" '
        f'style="background:#0e1117;border-radius:8px;">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.5" '
        f'points="{" ".join(points)}" />'
        f'<text x="{pad}" y="18" fill="#9ca3af" font-size="12">'
        f"{high:,.2f}</text>"
        f'<text x="{pad}" y="{height - 6}" fill="#9ca3af" font-size="12">'
        f"{low:,.2f}</text>"
        f"</svg>"
    )


TRADE_COLUMNS = (
    "side",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "stop_loss",
    "target",
    "lots",
    "points",
    "profit",
    "loss",
    "net_usd",
    "reason",
)


def _cell(value) -> str:
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _trade_row(trade: dict) -> dict:
    points = float(trade.get("points") or 0.0)
    row = dict(trade)
    row["profit"] = points if points > 0 else 0.0
    row["loss"] = points if points < 0 else 0.0
    return row


def render_trades(trades: list[dict]) -> None:
    rows_data = [_trade_row(trade) for trade in trades]
    total_points = sum(float(row["points"]) for row in rows_data)
    total_profit = sum(float(row["profit"]) for row in rows_data)
    total_loss = sum(float(row["loss"]) for row in rows_data)
    total_net = sum(float(row.get("net_usd") or 0.0) for row in rows_data)
    headers = "".join(f"<th style='text-align:left;padding:6px'>{column}</th>" for column in TRADE_COLUMNS)
    rows: list[str] = []
    for row in rows_data:
        cells = "".join(
            f"<td style='padding:6px'>{_cell(row.get(column, ''))}</td>"
            for column in TRADE_COLUMNS
        )
        rows.append(f"<tr>{cells}</tr>")
    totals = {
        "side": "TOTAL",
        "points": total_points,
        "profit": total_profit,
        "loss": total_loss,
        "net_usd": total_net,
    }
    total_cells = "".join(
        f"<td style='padding:6px'><b>{_cell(totals.get(column, ''))}</b></td>"
        for column in TRADE_COLUMNS
    )
    st.html(
        "<div style='overflow-x:auto'>"
        "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr style='border-top:2px solid #9ca3af'>{total_cells}</tr></tfoot>"
        "</table></div>"
    )
    st.caption(
        f"Profit: {total_profit:+.2f} pts · Loss: {total_loss:+.2f} pts · "
        f"Grand total: {total_points:+.2f} pts ({total_net:+,.2f} USD)"
    )


def render_result(result, m15_count: int, m1_count: int, days: int, warmup_days: float) -> None:
    st.caption(
        f"Trades from the last {days} day(s). "
        f"Loaded {warmup_days:g} extra warmup day(s) for swings/trend "
        f"({m15_count} 15m candles, {m1_count} 1m candles)."
    )
    render_metrics(result)
    st.subheader("Equity curve")
    render_equity_curve(result.equity)
    st.subheader("Trades")
    if result.trades:
        render_trades(result.trades)
    else:
        st.write("No entries matched the 15m sweep + 1m two-candle confirmation.")


def run_backtest(symbol: str, days: int, params: BacktestParams):
    status = st.empty()
    fetch_days = int(days + max(params.warmup_days, 0))
    status.info(f"Fetching 15-minute candles ({fetch_days} days including warmup)…")
    m15_rows = load_ohlcv(symbol, "15m", fetch_days)
    status.info(f"Fetching 1-minute candles ({fetch_days} days including warmup)…")
    m1_rows = load_ohlcv(symbol, "1m", fetch_days)
    status.info("Simulating trades…")
    result = run_m15_backtest(m15_rows, m1_rows, params)
    status.empty()
    return result, m15_rows, m1_rows


def render_rules(rule) -> None:
    with st.expander("Strategy rules"):
        st.markdown(f"**{rule.name}**")
        for section in ("setup_rules", "entry_rules", "exit_rules"):
            st.markdown(f"*{section.replace('_', ' ').title()}*")
            for item in getattr(rule, section):
                st.markdown(f"- {item}")


def main() -> None:
    st.set_page_config(page_title="15m Liquidity Grab Backtest", layout="wide")
    st.title("15-Minute Liquidity Grab Backtest")
    st.write(
        "Sweeps 15-minute swing highs/lows, then enters on a 1-minute two-candle "
        "reversal. Risk: 1% per trade, max 20 lots, 2.5R target from fill, "
        "stop to breakeven at 1R, stop the day at 3% loss."
    )
    rule = load_rule()
    symbol, days, params = sidebar_params(params_from_rule(rule.parameters))
    render_rules(rule)
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, m15_rows, m1_rows = run_backtest(symbol, days, params)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["backtest_result"] = result
        st.session_state["backtest_meta"] = (
            len(m15_rows),
            len(m1_rows),
            symbol,
            days,
            params.warmup_days,
        )

    stored = st.session_state.get("backtest_result")
    meta = st.session_state.get("backtest_meta")
    if stored is not None and meta is not None:
        if len(meta) == 4:
            m15_count, m1_count, used_symbol, used_days = meta
            used_warmup = 0.0
        else:
            m15_count, m1_count, used_symbol, used_days, used_warmup = meta
        st.success(f"Last run: {used_symbol}, last {used_days} day(s) of trades")
        render_result(stored, m15_count, m1_count, used_days, used_warmup)


if __name__ == "__main__":
    main()
