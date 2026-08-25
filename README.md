# Strategy Backtester

Backtest trading strategy rules on **Delta Exchange ETH futures** historical data.

## What it does

1. Loads trading rules from `data/strategies/*.json`
2. Downloads **ETHUSD 1d** candles from Delta Exchange
3. Backtests each technique on historical data
4. Saves a markdown report + JSON results

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Delta settings. Point `STRATEGY_RULES` at a JSON file in `data/strategies/` if you want a default other than `lqdty_liquidity.json`.

## Run with Streamlit UI

```bash
streamlit run app.py
```

Open the app, pick a strategy JSON in the sidebar, and click **Run Analysis**.

## Run full pipeline (CLI)

```bash
python main.py
```

Or with options:

```bash
python main.py --rules data/strategies/lqdty_liquidity.json --symbol ETHUSD --days 365
```

## Output

| File | Description |
|------|-------------|
| `data/strategies/*.json` | Strategy rules (source of truth) |
| `data/ohlcv/ETHUSD_1d.csv` | Delta Exchange candle data |
| `data/reports/{strategy}_report.md` | Backtest report |
| `data/reports/{strategy}_results.json` | Raw backtest metrics |

## Included strategy

| File | Strategy |
|------|----------|
| `data/strategies/lqdty_liquidity.json` | LQDTY liquidity (1D levels + 1m shorts) |

Add another JSON file under `data/strategies/` to backtest additional rules.

## Delta Exchange

- **India:** `https://api.india.delta.exchange` → symbol `ETHUSD`
- **Global:** `https://api.delta.exchange` → symbol `ETHUSDT`

No API key required for historical candle data.

## Disclaimer

For research and education only. Past performance does not guarantee future results.
