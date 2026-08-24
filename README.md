# 15m Previous-Day POC Live Strategy

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

Set symbol, lookback days, lots, and take-profit in the sidebar, then click **Run backtest**. The app pulls public Delta 15-minute candles (no API key) and simulates previous-day volume profile levels (POC / VAL / VAH) plus a 15-minute rejection.

## Live trading

```bash
python scripts/run_live_strategy.py --loop --enable
```

Each UTC session close builds a fixed-range volume profile on that complete day. The next day the bot waits for price to return to POC (or VAL / VAH), checks previous-day direction, and only enters after a 15-minute rejection candle.

For research only. Past performance does not guarantee future results.
