# 15m Liquidity Grab + 1m Confirmation

Backtests a 15-minute liquidity sweep with 1-minute two-candle reversal confirmation on **India Delta ETHUSD futures**. Candles are fetched live from `https://api.india.delta.exchange` on every run (no cache). Live signals use that same India feed; orders default to the demo/testnet account. **All timestamps are IST (UTC+5:30).**

## Strategy

1. Mark 15-minute swing highs and lows (fractal pivots).
2. Wait for a liquidity grab on a **closed 15-minute bar**:
   - Downside: wick at least 3 points below a swing low.
   - Upside: wick at least 3 points above a swing high.
3. Confirm on the 1-minute chart: two consecutive reversal candles with a body of at least 1.5 points. Enter when the second breaks the first (**market order** on Delta).
4. Close the full position at +10 points with a reduce-only maker limit. Stop sits 0.5 points beyond the grab extreme (max 35 points).

Stop sits just beyond the grab extreme. The exact thresholds come from the preset you pick.

## Tuned parameters

The original hand-picked settings lost money over 180 days (32% win rate, $122 net against a $259 drawdown), mostly because a 15-point stop cap rejected the majority of valid setups. `scripts/optimize.py` searches the parameter space instead, scoring every candidate across six 30-day folds so a config has to work in more than one market regime.

The shipped configuration lives in `src/presets.py` and is what live uses. Measured on 180 days of India-live ETHUSD at 100 lots with Delta India costs (taker 0.05%, maker 0.02%, scalper offer on). **Entry is a market order**, same as Delta live:

| Metric | Previous (1pt sweep) | **Now (3pt + 1.5 body)** |
| --- | --- | --- |
| Trades | 667 (~4/day) | **344 (~2/day)** |
| Win rate | 65.7% | **73.5%** |
| Gross / fees / net | $2,239 − $946 = $1,293 | **$1,290 − $478 = $812** |
| Fee share of gross | 42% | **37%** |
| Max drawdown | $84 | $88 |
| Folds profitable | 6/6 | **6/6** |
| Worst case (no scalper, taker exits, GST, 1pt slip) | −$75 | **+$92** |

Fewer, cleaner entries cut the fee bill in half. Total net is lower than the noisy 1-point version, but the edge per trade is larger ($2.36 vs $1.94) and it still profits if live fills slip a point.

Reproduce or re-tune:

```bash
python scripts/cache_history.py --days 180     # download once
python scripts/optimize.py --profile profit --folds 6 --train-frac 1.0
python scripts/compare_configs.py              # fold-by-fold table
python scripts/stress.py                       # cost sensitivity
python scripts/sensitivity.py                  # one-parameter-at-a-time plateaus
```

## Fees

Fees are still mostly **entry** (taker breakout). Live does not rest an entry limit — a buy at the 1m break crosses the ask — so do not enable “maker on entry” unless the live runner is changed to wait for a pullback.

- **Join the Scalper Offer.** Waives the closing fee on exits inside 30 minutes.
- **Keep maker take-profit limits.** Live already rests a reduce-only limit at +10.
- **Do not force-exit at 29 minutes.** Fees drop, net drops more.
- **Do not scale out.** Two exits ≈ two exit fees.

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

Set the symbol, pick a **start and end date** (IST), then click **Run backtest**. Every sidebar rule is pre-filled from the tuned strategy and can be overridden to test a variant. Results include a fee breakdown and a per-round-trip win rate alongside the per-fill tiles.

## Live (same rules)

Uses the same engine and the same parameters as the backtest. On each closed 1-minute bar it looks for a 3-point 15m grab + two 1m candles with 1.5-point bodies, then:

- Market-enters the full position (taker — same as a breakout on Delta)
- Rests a reduce-only maker limit on the full size at +10
- Rests a reduce-only stop on the full size

Put demo API keys in `.env`. Candles stay on India live; orders go to `DELTA_BASE_URL` (demo/testnet by default):

```bash
pip install -r requirements.txt
# Scan India-live candles only — no orders
python scripts/run_live.py --loop

# Place orders on the demo account
python scripts/run_live.py --live --loop
```

Alerts go to every address in `NOTIFY_EMAIL` (comma-separated) on buy/sell signals, live fills, 80% take-profits, and position closes.

```bash
python scripts/run_live.py --test-email
```

Create the API key on [Delta demo](https://demo.delta.exchange/app/account/manageapikeys) with **trading** enabled and this machine's IP whitelisted. Start with `--loop` (dry-run) and confirm signals match the Streamlit backtest before using `--live`.

For research and at your own risk. Past performance does not guarantee future results. Futures can lose more than your margin.
