# 15m Liquidity Grab + 1m Confirmation

Backtests a 15-minute liquidity sweep with 1-minute two-candle reversal confirmation on **India Delta ETHUSD futures**. Candles are fetched live from `https://api.india.delta.exchange` on every run (no cache). Live signals use that same India feed; orders default to the demo/testnet account. **All timestamps are IST (UTC+5:30).**

## Strategy

1. Mark 15-minute swing highs and lows (fractal pivots).
2. Wait for a liquidity grab on a **closed 15-minute bar**:
   - Downside: wick through a swing low and close back above it.
   - Upside: wick through a swing high and close back below it.
3. Confirm on the 1-minute chart: two consecutive reversal candles with a real body. Enter when the second breaks the first.
4. Scale out at the first target and let the rest run, with the stop at breakeven.

Stop sits just beyond the grab extreme. The exact thresholds come from the preset you pick.

## Tuned parameters

The original hand-picked settings lost money over 180 days (32% win rate, $122 net against a $259 drawdown), mostly because a 15-point stop cap rejected the majority of valid setups. `scripts/optimize.py` searches the parameter space instead, scoring every candidate across six 30-day folds so a config has to work in more than one market regime.

The shipped configuration lives in `src/presets.py`. Measured on 180 days of India-live ETHUSD at 100 lots with Delta India costs (taker 0.05%, maker 0.02%, scalper offer on):

| Metric | Value |
| --- | --- |
| Trades | 667 (~4/day) |
| Win rate | 65.7% |
| Gross / fees / net | $2,239 − $946 = **$1,293** |
| Max drawdown | $84 |
| Profit factor | 1.51 |
| Folds profitable | 6 of 6 (+$184 to +$287 each) |

The edge is $1.94 per trade, so costs matter. Under worst-case assumptions (no scalper offer, taker exits, 18% GST) it still makes $592, but adding 1 point of slippage turns it into −$75. Join the Scalper Offer and use limit exits.

Reproduce or re-tune:

```bash
python scripts/cache_history.py --days 180     # download once
python scripts/optimize.py --profile profit --folds 6 --train-frac 1.0
python scripts/compare_configs.py              # fold-by-fold table
python scripts/stress.py                       # cost sensitivity
python scripts/sensitivity.py                  # one-parameter-at-a-time plateaus
```

## Fees

Fees are 42% of gross profit, and **entry fees are 74% of them**. A breakout entry is always taker: a buy limit at the break level crosses the ask, so the maker rebate is unreachable without switching to a pullback entry that may not fill. What you can control:

- **Join the Scalper Offer.** It waives the closing fee on exits inside 30 minutes and is worth $175 over the sample.
- **Keep maker exits on.** A resting reduce-only limit pays 0.02% instead of 0.05%, worth another $275.
- **Exit in one fill.** Scaling out doubles exit fills and roughly doubles exit fees, which is why the tuned strategy takes the whole position off at the target.

Only 44% of exits currently land inside the scalper window (median hold is 37 minutes). Forcing an exit at 29 minutes does push that to 100% and cuts fees 22%, but it cuts gross profit more — net falls from $1,293 to $886. The optimizer reached the same conclusion independently and left `max_hold_minutes` at 0. The knob is in the sidebar if you want to see it yourself.

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

Uses the same engine and the same parameters as the backtest. On each closed 1-minute bar it looks for a 15-minute grab + two-candle confirmation, then:

- Market-enters the full position
- Rests the scale-out portion as a reduce-only maker limit at the first target
- Rests a reduce-only stop on the full position
- After the scale-out fills, moves the remainder to breakeven and targets the runner level

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
