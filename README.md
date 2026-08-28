# 15m Liquidity Grab + 1m Confirmation

Backtests a 15-minute liquidity sweep with 1-minute two-candle reversal confirmation on **India Delta ETHUSD futures**. Candles are fetched live from `https://api.india.delta.exchange` on every run (no cache).

## Strategy

1. Mark 15-minute swing highs and lows (fractal, 2 bars left/right).
2. Wait for a liquidity grab on a **closed 15-minute bar**:
   - Downside: wick at least 3 points below a swing low and close back above it.
   - Upside: wick at least 3 points above a swing high and close back below it.
3. Confirm on the 1-minute chart: two consecutive reversal candles with a real body. Enter when the second breaks the first.
4. Size **100 lots**. Take **80 lots** off at +30 points. Move the remaining **20 lots** to breakeven and target +90.

Stop sits 1 point beyond the grab extreme, capped at 15 points.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Public candle history does not need API keys.

## Backtest

```bash
streamlit run app.py
```

Set symbol (`ETHUSD`), lookback, and fees, then click **Run backtest**.

## Live (same rules)

Uses the same engine as the backtest. On each closed 1-minute bar it looks for a 15-minute grab + two-candle confirmation, then:

- Market-enters 100 lots
- Rests 80 lots as a reduce-only limit at +30 (maker)
- Rests a reduce-only stop on the full 100 lots
- After the 80% fill, moves the remaining 20 lots to breakeven and targets +90

Put your India API key and secret in `.env`, then:

```bash
pip install -r requirements.txt
# Scan only — no orders
python scripts/run_live.py --loop

# Real orders on your Delta account
python scripts/run_live.py --live --loop
```

Alerts go to every address in `NOTIFY_EMAIL` (comma-separated) on buy/sell signals, live fills, 80% take-profits, and position closes.

```bash
python scripts/run_live.py --test-email
```

Create the API key on Delta with **trading** enabled. Start with `--loop` (dry-run) and confirm signals match the Streamlit backtest before using `--live`.

For research and at your own risk. Past performance does not guarantee future results. Futures can lose more than your margin.
