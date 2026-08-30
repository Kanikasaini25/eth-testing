# Delta India funding cash-and-carry

Both-sided funding hedge on **India Delta** perpetuals. Each book pairs a perp with its INR spot pair and is sized to the same USD notional. Candles and funding come from `https://api.india.delta.exchange`.

## The trade

Price is hedged away, so profit is funding collected minus the round trip.

- Funding **positive** (`carry`): buy spot, short the perp.
- Funding **negative** (`reverse`): sell spot, long the perp.

## Rules

- Last **2** settlements with |rate| **≥ 0.005%**, same sign.
- Enter only if expected funding over a typical hold beats the round-trip fee (2 futures + 2 spot).
- Futures legs are **post-only maker**; spot stays taker.
- Exit after **2 consecutive opposite-sign readings**, not the first flip.
- Skip new entries in the last 30 minutes before 00/08/16 UTC (5:30 / 13:30 / 21:30 IST) unless |rate| ≥ 0.02%.

Live clocks and logs use **Asia/Kolkata (IST, UTC+5:30)**. Exchange funding still prints at 00/08/16 UTC.

## Which books to trade

A carry only pays if funding stays on one side long enough to outrun the round trip. Over the last 365 days at ~$2,450 notional each:

| Symbol | One-sided | Fills | Net | Verdict |
|---|---|---|---|---|
| BTCUSD | 78% | 4 | +$747 | trade |
| ETHUSD | 78% | 3 | +$686 | trade |
| XRPUSD | 56% | 24 | +$745 | skip — one trade made it all |
| SOLUSD | 54% | 120 | −$334 | skip — churned into $384 of fees |

`SYMBOLS` defaults to `ETHUSD,BTCUSD`. The runner screens every book on startup and drops anything under **75% one-sided**; `--skip-screen` overrides.

```bash
python scripts/screen_funding.py --symbols ETHUSD,BTCUSD,SOLUSD,XRPUSD
```

## Sizing

1 lot is the contract value, not 1 coin: `ETHUSD` 0.01 ETH, `BTCUSD` 0.001 BTC, `SOLUSD`/`XRPUSD` 1 coin. Set `NOTIONAL_USD` and lots are derived per symbol, so books stay comparable.

At $2,450: ETHUSD 100 lots (1 ETH), BTCUSD 31 lots (0.031 BTC).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Public candles and funding do not need API keys.

## Backtest

```bash
streamlit run app.py
```

Pick a symbol and lookback, then **Run backtest**.

## Live

```bash
# Scan only, both books
python scripts/run_live.py --loop

# Real orders
python scripts/run_live.py --live --loop

# One book, fixed size
python scripts/run_live.py --symbols BTCUSD --lots 31
```

Create the API key with **trading** enabled. Start in dry-run. Each symbol keeps its own state file under `data/live/`.

`python scripts/run_live.py --test-email` sends a mail to `NOTIFY_EMAIL`.

## Known constraints

- **Signals come from the `FUNDING:` candle series, not the ticker.** The ticker's `funding_rate` field disagrees with that series in sign as well as level, so trading off the ticker inverts every entry.
- **The demo/testnet account cannot validate this strategy.** Testnet funding is pinned at a constant `+0.01%` and there is no `ETH_INR` book. Point `DELTA_BASE_URL` at testnet and `SPOT_SYMBOL` at `ETH_USDT` if you only want to rehearse order plumbing; signals still come from live India either way.
- Reverse carry needs spot inventory to sell.
- If the spot leg fails after the futures leg fills, the futures position is unwound rather than left naked, and an alert is sent.
- Backtests assume maker fills at the bar close; live rests a post-only futures order and only hedges spot after it fills.

For research and at your own risk. Futures can lose more than your margin. Cash-and-carry still has basis, INR/USD, and execution risk.
