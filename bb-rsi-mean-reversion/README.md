# ETH BB + RSI Mean Reversion (isolated)

Standalone 1-minute mean-reversion bot for **ETH perpetual futures** on Delta Exchange testnet. It does **not** import, start, or change the existing LQDTY / YouTube backtester code.

Do not run this on the same Delta account/position as another ETH bot.

## Rules

| Item | Value |
|---|---|
| Timeframe | 1m candles |
| Bands | 20-period **SMA** Bollinger, 2.0 stdev (no EMA) |
| RSI | 14-period **Cutler's RSI** (SMA of gains/losses, not Wilder/EMA) |
| Long | 1m close below or piercing the lower band **and** RSI < 30 |
| Short | 1m close above or piercing the upper band **and** RSI > 70 |
| Session | **Opens only (IST):** London **12:30–2:00 PM**, US **7:00–9:30 PM** |
| 1h filter | Fade the last 60 1m bars: long after a **down** hour, short after an **up** hour |
| Re-entry | After a **loss**: wait **15 minutes from the loss entry**, then fade the 1h trend (no new RSI extreme needed). Max **2 SL per open**. After a **profit**: wait for the **next open** |
| Daily cap | 4 trades per IST day |
| Kill-switch | Flatten + halt if daily PnL ≤ **-$14** |
| Stop | **100 lots** every trade; SL **-$3.50** (3.50 pts at 1 ETH) |
| Take profit | Limit **+$10 net of fees**. +$5 lock **off** (cannot cover a stop after fees). Cap **+$20 net** |

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

The sidebar downloads public **1m ETH** candles from Delta (no API key required), then runs the same SMA Bollinger + RSI rules, session filter, $3.50 stop sizing, 4-trade cap, and -$14 kill-switch.

The UI shows:

- Overview metrics (total P/L, wallet, win rate, drawdown)
- Charts: Delta-style IST candlesticks (OHLC + volume + SMA Bollinger + RSI + trade markers), plus equity / P/L SVGs
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
