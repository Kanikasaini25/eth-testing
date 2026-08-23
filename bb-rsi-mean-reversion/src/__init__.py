"""
ETH 1m SMA Bollinger + RSI mean-reversion bot (Delta testnet).

This package is fully isolated. It does not import or modify the LQDTY live
strategy, backtests, or Streamlit app. Use a dedicated API key / subaccount —
do not run it on the same ETH position as another bot.
"""

from __future__ import annotations

# Isolated package — no shared live-strategy imports.
