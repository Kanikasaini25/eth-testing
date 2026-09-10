from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st

from src.config import get_env, get_market_data_base_url, get_trade_base_url
from src.delta_trading import DeltaTradingClient, trade_network_label
from src.live import LiveGrabRunner, live_params


def _account_status(symbol: str) -> tuple[bool, str]:
    broker = DeltaTradingClient(symbol=symbol)
    snap = broker.test_connection()
    net = trade_network_label(snap.base_url)
    if not snap.connected:
        extra = ""
        if "ip_not_whitelisted" in (snap.error or ""):
            extra = (
                " Whitelist this machine's IP on the demo API key at "
                "https://demo.delta.exchange/app/account/manageapikeys"
            )
        return False, f"Not connected on {net}: {snap.error}.{extra}"
    size = 0
    if snap.position:
        size = int(snap.position.get("size") or 0)
    return True, f"Connected · {net} · {snap.symbol} · position {size} lots"


def main() -> None:
    st.set_page_config(page_title="Live Demo", layout="wide")
    st.title("India live signals · demo orders")
    data_url = get_market_data_base_url()
    trade_url = get_trade_base_url()
    st.write(
        "Candles and entry signals come from **India live**. "
        "Filled orders go to the **demo/testnet** account."
    )
    st.caption(f"Market data `{data_url}`")
    st.caption(f"Orders `{trade_url}` ({trade_network_label(trade_url)})")

    symbol = st.sidebar.text_input("Symbol", value=get_env("DELTA_SYMBOL", "ETHUSD")).strip().upper()
    lots = st.sidebar.number_input("Trade size (lots)", min_value=1, value=100, step=1)
    runner = LiveGrabRunner(params=live_params(lots=int(lots)), symbol=symbol)

    connected, account_line = _account_status(symbol)
    if connected:
        st.success(account_line)
    else:
        st.error(account_line)

    col1, col2 = st.columns(2)
    scan = col1.button("Scan India live", type="primary")
    place = col2.button("Place demo order if signal", disabled=not connected)
    if place and not connected:
        st.warning("Demo account is not connected, so no order was sent.")
        return

    if not scan and not place:
        st.info("Scan pulls closed India-live 15m/1m bars. Place sends a market order on demo.")
        return

    dry_run = not place
    status = st.empty()
    status.info("Fetching India-live candles and scanning the last closed 1m bar…")
    try:
        lines = runner.tick(dry_run=dry_run)
    except Exception as exc:
        status.empty()
        st.error(f"Tick failed: {exc}")
        return
    status.empty()
    mode = "Demo order tick" if place else "India-live scan (no orders)"
    st.subheader(mode)
    st.code("\n".join(lines), language="text")


main()
