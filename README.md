# 15m Liquidity Grab + Hammer/Shooting Star

Backtests and live-scans strategies on **India Delta LIVE** candles (`https://api.india.delta.exchange` — never testnet/demo history).

## Gold / XAUUSD — which broker?

| Want | Use | Notes |
|------|-----|--------|
| Gold on **Delta India** | `PAXGUSD` (or `XAUTUSD`) | Tokenized gold perpetual. Classic **XAUUSD is not listed** on Delta. |
| Classic **XAUUSD** CFD | **MT5 / PDMBulls** | `scripts/run_mt5_local.py` or `mql5/` EA |
| India exchange gold | **Angel One MCX** (e.g. GOLDM) | Not XAUUSD; would need a new SmartAPI integration |

If you pass `--symbol XAUUSD` to the Delta scripts, it is aliased to **PAXGUSD**.

## Strategy (Streamlit / pattern)

**Hammer / Shooting Star entry** plus gold production overlays (all **USD**, India LIVE candles):

1. **Trend regime** — EMA(50) side filter, ADX ≥ 20, Donchian(20) context  
2. **Entry** — Hammer (BUY) / Shooting Star (SELL) + 1m confirm  
3. **Mean-reversion** — Bollinger extreme **or** RSI 25/75  
4. **ATR risk** — stops/targets scale with ATR(14)  
5. **Sessions (UTC)** — London 07–10 or London/NY overlap 12–16  

Toggle any overlay via `.env` `USE_*` flags. Scale out at T1/T2; close at T3.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Public candle history does not need API keys.

## Backtest (live production candles)

```bash
streamlit run app.py
```

Select **PAXGUSD** (gold) or ETHUSD in the sidebar, set lookback, then **Run backtest**.

## Live on Delta (same candle source)

```bash
# Scan only — no orders (gold)
python scripts/run_live.py --loop --symbol PAXGUSD

# Real orders (needs live India keys in .env, not testnet)
python scripts/run_live.py --live --loop --symbol PAXGUSD --lots 100
```

Set `DELTA_BASE_URL=https://api.india.delta.exchange` and production API keys for real orders. Candles are always India LIVE regardless of `DELTA_BASE_URL`.

Alerts go to every address in `NOTIFY_EMAIL` (comma-separated).

```bash
python scripts/run_live.py --test-email
```

## Local MT5 / PDMBulls (true XAUUSD)

Trade Hammer / Shooting Star on your **PDMBulls** account from this laptop.

1. Install **MetaTrader 5** from PDMBulls and log in.
2. Keep the MT5 terminal **open and connected**.
3. On **Windows** (`MetaTrader5` package is Windows-only):

```bash
pip install MetaTrader5
```

4. Put credentials in `.env` with `MT5_SYMBOL=XAUUSD`.
5. Run:

```bash
python scripts/run_mt5_local.py --check
python scripts/run_mt5_local.py --loop              # dry-run
python scripts/run_mt5_local.py --live --loop       # place orders
```

On Linux, use the MQL5 EA in `mql5/` instead (see `mql5/README.md`).

For research and at your own risk. Past performance does not guarantee future results.
