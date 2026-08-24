#!/usr/bin/env python3
"""Standalone Streamlit entry for 1H Liquidity Reversal (optional).

Prefer:  streamlit run app.py
Or this: streamlit run app_1h_liquidity_reversal.py
"""

from __future__ import annotations

import streamlit as st

from src.ui.liquidity_reversal_1h_app import render_liquidity_reversal_app

st.set_page_config(
    page_title="1H Liquidity Reversal",
    page_icon="📈",
    layout="wide",
)

render_liquidity_reversal_app()
