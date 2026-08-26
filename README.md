# Strategy Backtester

Backtest trading strategy rules on **Delta Exchange ETH futures**.

## What it does

1. Loads trading rules from `data/strategies/*.json`
2. Downloads ETHUSD candles from Delta Exchange
3. Backtests **LQDTY (1d/1m transcript rules)** and **15m POC** in separate Streamlit tabs

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your Delta settings.

- `STRATEGY_RULES` — 1d/1m LQDTY JSON (default `lqdty_liquidity.json`)
- `STRATEGY_M15_RULES` — 15m POC JSON (default `wI9b968AvW8_rules.json`)

## Run with Streamlit UI

```bash
streamlit run app.py
```

Tabs:

- **Demo Account** — wallet, position, test orders
- **Backtest 1d / 1m** — LQDTY previous-day high/low, 1m confirmation, swing targets
- **Backtest 15m** — previous-day POC reaction

Each backtest tab has its own Run button, rules file, and saved results. Running one does not overwrite the other.

Both backtests download candles from **India live** (`https://api.india.delta.exchange`) — real ETHUSD history. The Demo Account / live bot still uses `DELTA_BASE_URL` (testnet unless you change it).

## Run live from CLI

```bash
python scripts/run_live_strategy.py --strategy lqdty --loop --enable
python scripts/run_live_strategy.py --strategy m15 --loop --enable
```

## Run full pipeline (CLI)

```bash
python main.py --rules data/strategies/lqdty_liquidity.json --symbol ETHUSD --days 365
python main.py --rules data/strategies/wI9b968AvW8_rules.json --symbol ETHUSD --days 90
```

## Output

| File | Description |
|------|-------------|
| `data/strategies/*.json` | Strategy rules (source of truth) |
| `data/ohlcv/ETHUSD_1d.csv` | Daily candles |
| `data/ohlcv/ETHUSD_1m.csv` | 1m candles (LQDTY) |
| `data/ohlcv/ETHUSD_15m.csv` | 15m candles (POC) |
| `data/reports/{strategy}_report.md` | Backtest report |
| `data/reports/{strategy}_results.json` | Raw backtest metrics |

## Included strategies

| File | Strategy |
|------|----------|
| `data/strategies/lqdty_liquidity.json` | LQDTY liquidity from the 1d/1m transcript (PDH/PDL + 1m confirmation) |
| `data/strategies/wI9b968AvW8_rules.json` | 15m previous-day POC reaction |

## Delta Exchange

- **India demo:** `https://cdn-ind.testnet.deltaex.org` → symbol `ETHUSD`
- **India live:** `https://api.india.delta.exchange` → symbol `ETHUSD`
- **Global:** `https://api.delta.exchange` → symbol `ETHUSDT`

No API key required for historical candle data. Demo trading needs `DELTA_API_KEY` and `DELTA_API_SECRET`.

## Disclaimer

For research and education only. Past performance does not guarantee future results.
