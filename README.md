# 15m Liquidity Grab Live Strategy

On the server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put Delta keys in `.env`. Keep `data/strategies/wI9b968AvW8_rules.json`.

## Backtest (Streamlit)

```bash
streamlit run app.py
```

Set symbol, lookback days, lots, and take-profit in the sidebar, then click **Run backtest**. The app pulls public Delta candles (no API key) and simulates the 15-minute sweep + 1-minute two-candle reversal.

## Live trading

```bash
python scripts/run_live_strategy.py --loop --enable
```

The bot marks 15-minute swing highs and lows, waits for a liquidity grab, then enters on a 1-minute two-candle reversal (100 lots, 15-point take profit).

For research only. Past performance does not guarantee future results.
