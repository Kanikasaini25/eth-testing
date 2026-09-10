# ETH Volume-Bias Strategy

Live ETH strategy on **Delta Exchange India**: measure buy vs sell volume through the India day, then at **7:00 PM IST** wait for one pullback and trade with the day's market power.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set `DELTA_API_KEY`, `DELTA_API_SECRET`, and (if needed) `DELTA_BASE_URL` in `.env`.

## Run

```bash
streamlit run app.py
```

Or from the CLI:

```bash
python scripts/run_live_strategy.py --enable --loop
```

Open the **Backtest** tab, pick an IST date range, and click **Run backtest**. It pulls India-live **15m** and **1m** candles and shows trades, points, P/L, win rate, and wallet.

## Strategy

1. Watch India-live ETH volume until 19:00 IST (buy-side vs sell-side candle volume)
2. Lock the stronger side
3. Wait for one **15m pullback** against that side
4. After the 15m pullback closes, wait for a **1m confirmation** candle with the day's power, then enter
5. Stop = 15m pullback wick high/low
6. Targets: **+1%** keep wick SL; **+2%** move SL to +1%; **+3%** SL to +2%; **+4%** SL to +3%; **+5%** close the full position
7. If the stop hits, wait for the **next** 15m pullback and try again. After **2 wins** or **2 losses** in the same India day, stop trading until the next day.

## Disclaimer

For research and education only. Past performance does not guarantee future results.
