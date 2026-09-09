# Hammer / Shooting Star on Linux + PDMBulls MT5

You do **not** need a Delta India account.

| Approach | Works on your Linux laptop? |
|----------|-----------------------------|
| `pip install MetaTrader5` | No (Windows only) |
| Delta India API | Needs a Delta account |
| **MQL5 Expert Advisor inside MT5** | **Yes — use this** |

The EA runs **inside MetaTrader 5** on your PDMBulls demo/live account. No Python package, no cloud server, no Delta.

## File

`mql5/HammerShootingStar_PDM.mq5`

## Install (Linux laptop)

1. Install MetaTrader 5 for Linux (or Wine) from PDMBulls and log into your **demo**.
2. In MT5: **File → Open Data Folder → `MQL5/Experts/`**
3. Copy `HammerShootingStar_PDM.mq5` into that `Experts` folder.
4. Open **MetaEditor** (F4) → open the file → click **Compile** (F7).
5. In MT5 Navigator → Expert Advisors → drag **HammerShootingStar_PDM** onto **XAUUSD M1** chart.
6. Inputs:
   - `InpLots` = `0.10` (or your size)
   - `InpPatternTF` = `15 minutes` (or 5/30/60)
   - `InpTradeEnabled` = `false` first (signals only in Experts journal)
7. Enable AutoTrading (toolbar green button).
8. When Journal looks correct, set `InpTradeEnabled = true`.

## What it does

- Hammer in downtrend → wait for 1m green close above hammer high → **BUY**
- Shooting Star in uptrend → wait for 1m red close below star low → **SELL**
- No RSI / EMA / volume filters
- SL at pattern extreme
- Book ~40% at T1, trail SL; book again at T2; close all at T3

## Keep it running

Leave MT5 open on your laptop. Sleep/close = trading stops.

## Optional later

Create a Delta account only if you want the Python Streamlit / `run_live.py` path. For PDMBulls, the EA is enough.
