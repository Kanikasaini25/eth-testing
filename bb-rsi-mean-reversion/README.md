# ETH Session Open (isolated)

Standalone 1-minute session-open bot for **ETH perpetual futures** on Delta Exchange testnet. It does **not** import, start, or change the existing LQDTY / YouTube backtester code.

Do not run this on the same Delta account/position as another ETH bot.

## Rules

| Item | Value |
|---|---|
| Timeframe | 1m candles |
| Long | US open: **2 green 1m candles** back to back |
| Short | London open: **2 red 1m candles** back to back |
| Filters | **None** — no Bollinger, RSI, or 1h fade |
| Session | **Opens only (IST):** London **12:30–2:00 PM**, US **7:00–9:30 PM** |
| Re-entry | After a **loss**: wait **15 minutes**, then the same 2-candle pattern. Max **2 SL per open**. After a **profit**: wait for the **next open** |
| Daily cap | 4 trades per IST day |
| Kill-switch | Flatten + halt if daily PnL ≤ **-$14** |
| Stop | **100 lots**. London SL = **first red candle high** (retry: one tick above). US SL = **first green candle low** (retry: one tick below) |
| Take profit | Limit **+$10 net of fees**. +$5 lock **off**. Cap **+$20 net** |

## Setup

```bash
cd bb-rsi-mean-reversion
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put `DELTA_API_KEY` and `DELTA_API_SECRET` in `.env`. If those variables already exist in the repo-root `.env`, they are loaded as a fallback.

Default sandbox:

- REST: `https://cdn-ind.testnet.deltaex.org`
- Symbol: `ETHUSD` (India). Use `ETHUSDT` on global if that is your contract.

## Backtest UI

```bash
cd bb-rsi-mean-reversion
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The sidebar downloads **fresh** public **1m ETH** candles from Delta on every **Run backtest** click (no API key, no candle cache), then runs the same session-open rules, $3.50 stop sizing, 4-trade cap, and -$14 kill-switch.

The UI shows:

- Overview metrics (total P/L, wallet, win rate, drawdown)
- Charts: Delta-style IST candlesticks (OHLC + volume + trade markers + R:R), plus equity / P/L SVGs
- Full trade log with a **GRAND TOTAL** row
- IST daily totals with a **GRAND TOTAL** row

Max window is 30 days of 1m data (~43,200 candles). India Live is recommended for historical candles.

## Run live bot

```bash
# Live loop (places orders when enabled credentials are set)
python main.py

# Scan only — no orders
python main.py --dry-run

# Single tick
python main.py --once --dry-run
```

State is stored in `data/{SYMBOL}_bb_rsi_state.json` (separate from LQDTY live state). Logs go to stdout and `logs/bb_rsi.log`.

## Tests

```bash
cd bb-rsi-mean-reversion
python -m unittest discover -s tests -t .
```

## Notes

- Open positions are still managed outside the window (stops, TP, kill-switch). Only **new entries** are gated.
- Every entry is **100 lots** (1 ETH). Stop is 3.50 pts = **-$3.50** gross. TP is **+$10 net** (price target is widened by the round-trip taker fee).
- P/L is **net of Delta taker fees**: **0.05% of notional on entry** and **0.05% on exit**. At ETH $3,500 that is about **$1.75 + $1.75** per 100-lot round trip.
- Native bracket SL/TP is attempted first; if the testnet rejects it, the bot places a market entry plus reduce-only stop and take-profit.
