from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.backtest import BacktestParams, params_from_rule, run_poc_backtest
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


def load_ohlcv(symbol: str, resolution: str, days: int) -> list[dict]:
    client = DeltaExchangeClient(base_url=CANDLE_API_URL)
    return client.fetch_historical_ohlcv(symbol=symbol, resolution=resolution, days=days)


def sidebar_params(defaults: BacktestParams) -> tuple[str, int, BacktestParams]:
    st.sidebar.header("Backtest settings")
    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD"))
    days = st.sidebar.select_slider(
        "Lookback days",
        options=[7, 14, 21, 30, 60, 90, 180, 365, 730, 1095, 1460],
        value=365,
    )
    st.sidebar.caption(
        "365 = 1 year, 730 = 2 years, 1095 = 3 years, 1460 = 4 years. "
        "3–4 years can take several minutes to download."
    )
    lots = st.sidebar.number_input("Max lots", min_value=1, value=defaults.position_lots, step=1)
    risk_pct = st.sidebar.number_input(
        "Risk per trade (%)", min_value=0.1, value=float(defaults.risk_pct_per_trade), step=0.1, format="%.1f"
    )
    daily_loss = st.sidebar.number_input(
        "Max daily loss (%)", min_value=0.0, value=float(defaults.daily_loss_pct), step=0.5, format="%.1f"
    )
    target = st.sidebar.number_input(
        "Min take profit (points)", min_value=1.0, value=float(defaults.target_points), step=1.0
    )
    away = st.sidebar.number_input(
        "Must first leave POC by (points)", min_value=0.0, value=float(defaults.min_away_points), step=1.0
    )
    sweep = st.sidebar.number_input(
        "Min wick through POC (points)", min_value=0.0, value=float(defaults.min_sweep_points), step=0.5
    )
    bin_size = st.sidebar.number_input(
        "Volume profile bin size", min_value=0.1, value=float(defaults.bin_size), step=0.1, format="%.1f"
    )
    min_sl = st.sidebar.number_input("Min stop (points)", min_value=0.0, value=float(defaults.min_sl_points), step=0.5)
    max_sl = st.sidebar.number_input("Max stop (points)", min_value=0.0, value=float(defaults.max_sl_points), step=0.5)
    min_rr = st.sidebar.number_input(
        "Min reward:risk", min_value=0.0, value=float(defaults.min_reward_to_risk), step=0.1, format="%.1f"
    )
    reward_r = st.sidebar.number_input(
        "Reward multiple (R)", min_value=0.0, value=float(defaults.reward_r_multiple), step=0.5, format="%.1f"
    )
    use_htf = st.sidebar.checkbox("Also require previous-day direction", value=defaults.use_htf_bias)
    require_return = st.sidebar.checkbox(
        "Wait for price to return to POC (do not fade chop)", value=defaults.require_return
    )
    require_pullback = st.sidebar.checkbox(
        "Only fade pullbacks vs the day's open (do not chase)",
        value=defaults.require_open_pullback,
    )
    skip_monday = st.sidebar.checkbox("Skip Mondays", value=defaults.skip_monday)
    max_range = st.sidebar.number_input(
        "Skip if today already moved (points)",
        min_value=0.0,
        value=float(defaults.max_intraday_range),
        step=10.0,
    )
    trade_poc = st.sidebar.checkbox("Trade POC", value=defaults.trade_poc)
    trade_val = st.sidebar.checkbox("Trade value area low", value=defaults.trade_val)
    trade_vah = st.sidebar.checkbox("Trade value area high", value=defaults.trade_vah)
    use_session = st.sidebar.checkbox("Trade only 08:00–20:00 UTC", value=defaults.use_session_filter)
    use_be = st.sidebar.checkbox("Move stop to breakeven at 1.5R", value=defaults.move_stop_to_breakeven)
    max_day = st.sidebar.number_input("Max trades per day", min_value=0, value=int(defaults.max_trades_per_day), step=1)
    wallet = st.sidebar.number_input(
        "Starting wallet (USD)", min_value=100.0, value=float(defaults.starting_wallet_usd), step=100.0
    )
    st.sidebar.caption(
        "Delta ETHUSD: 1 lot = 0.01 ETH. $10,000 at ~$1,565 is about 100 lots, not 6. "
        "Size is still capped so notional never exceeds this wallet (1x)."
    )
    leverage = st.sidebar.number_input(
        "Max leverage",
        min_value=1.0,
        max_value=5.0,
        value=float(defaults.max_leverage),
        step=0.5,
        format="%.1f",
    )
    fee = st.sidebar.number_input(
        "Fee per side (%)", min_value=0.0, value=float(defaults.fee_pct_per_side), step=0.01, format="%.3f"
    )
    params = BacktestParams(
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
        max_trades_per_day=int(max_day),
        use_htf_bias=bool(use_htf),
        risk_pct_per_trade=float(risk_pct),
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


def render_trades(trades: list[dict]) -> None:
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
    st.html(
        "<div style='overflow-x:auto'><table style='width:100%;border-collapse:collapse;font-size:13px'>"
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody>"
        f"<tfoot><tr style='border-top:2px solid #9ca3af'>{total_cells}</tr></tfoot></table></div>"
    )
    st.caption(
        f"Profit: {total_profit:+.2f} pts · Loss: {total_loss:+.2f} pts · "
        f"Fees: {total_fees:,.2f} USD · Net P/L: {total_net:+,.2f} USD. "
        f"Delta ETHUSD: 1 lot = 0.01 ETH ($0.01 per point). Size USD is capped at the starting wallet (1x)."
    )


def render_result(result, m15_count: int, days: int, warmup_days: float) -> None:
    st.caption(
        f"Trades from the last {days} day(s). Loaded {warmup_days:g} extra day(s) for previous-day "
        f"volume profile ({m15_count} 15m candles)."
    )
    render_metrics(result)
    st.subheader("Equity curve")
    render_equity_curve(result.equity)
    st.subheader("Trades")
    if result.trades:
        render_trades(result.trades)
    else:
        st.write(
            "No 15m POC return-and-reject setups in this window. "
            "Try a longer lookback — 1 year is the default."
        )


def run_backtest(symbol: str, days: int, params: BacktestParams):
    status = st.empty()
    fetch_days = int(days + max(params.warmup_days, 1))
    status.info(
        f"Fetching fresh 15-minute candles from Delta ({fetch_days} days including previous session)…"
    )
    m15_rows = load_ohlcv(symbol, "15m", fetch_days)
    status.info("Simulating previous-day volume profile trades…")
    result = run_poc_backtest(m15_rows, params)
    status.empty()
    return result, m15_rows


def render_rules(rule) -> None:
    with st.expander("Strategy rules"):
        st.markdown(f"**{rule.name}**")
        for section in ("setup_rules", "entry_rules", "exit_rules"):
            st.markdown(f"*{section.replace('_', ' ').title()}*")
            for item in getattr(rule, section):
                st.markdown(f"- {item}")


def main() -> None:
    st.set_page_config(page_title="15m Previous-Day POC Backtest", layout="wide")
    st.title("15-Minute Previous-Day POC Backtest")
    st.write(
        "Marks each UTC session, builds a fixed-range volume profile on the previous day, "
        "then waits for price to leave POC and come back. A 15-minute wick through POC that "
        "closes back on the approach side is the entry — VAL/VAH are not auto-traded."
    )
    rule = load_rule()
    symbol, days, params = sidebar_params(params_from_rule(rule.parameters))
    render_rules(rule)
    if st.sidebar.button("Run backtest", type="primary"):
        try:
            result, m15_rows = run_backtest(symbol, days, params)
        except Exception as exc:
            st.error(f"Backtest failed: {exc}")
            return
        st.session_state["poc_backtest_result"] = result
        st.session_state["poc_backtest_meta"] = (len(m15_rows), symbol, days, params.warmup_days)

    stored = st.session_state.get("poc_backtest_result")
    meta = st.session_state.get("poc_backtest_meta")
    if stored is not None and meta is not None:
        m15_count, used_symbol, used_days, used_warmup = meta
        st.success(f"Last run: {used_symbol}, last {used_days} day(s) of trades")
        render_result(stored, m15_count, used_days, used_warmup)


if __name__ == "__main__":
    main()
