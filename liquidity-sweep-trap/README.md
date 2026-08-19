# Liquidity Sweep / Trap

Standalone backtesting project for the **Liquidity → Sweep/Trap → Confirmation** strategy.

This folder is **independent** of the parent `youtube/` project — it does not import or reuse any code from there.

## Strategy Summary

| Setup | Event | Trade |
|-------|-------|-------|
| Liquidity below price | Sweep + trap + bullish confirmation | **LONG** |
| Liquidity above price | Sweep + trap + bearish confirmation | **SHORT** |
| Touch only / no confirmation | Wait | **NO TRADE** |

**Flow:** Identify Liquidity → Wait for Price to Reach It → Let Traders Get Trapped / Liquidity Get Taken → Wait for Entry Confirmation → Enter 100 lots → Exit 50 lots at +5 points → Exit remaining 50 lots at +15 points.

The most important rule: **price touching liquidity is not an entry.**

## Timeframe Map

This project uses only this mapping:

| Analysis timeframe | Entry timeframe | Typical holding duration |
|--------------------|-----------------|--------------------------|
| 15 min – 1 hour | 1 min | 10–30 min |

Default: **15 minute analysis / 1 minute entry**. Time-stop at 30 minutes if targets are not hit.

## Exits

| Event | Lots | Price |
|-------|------|-------|
| Entry | 100 | Confirmation close |
| First profit | 50 (50%) | +5 points |
| Second profit | remaining 50 (50%) | +15 points |
| Stop | any open lots | Beyond the sweep wick |

## Confirmation rule (implementation choice)

The source description does not give an exact candle-by-candle trigger or stop formula. This project uses a documented rule so the backtest is testable:

1. **Sweep:** entry-timeframe wick pierces the nearest liquidity level, then that candle closes back inside the level.
2. **Trap still valid:** later candles must not make a new extreme beyond the sweep wick.
3. **Confirmation:** a reversal candle with a meaningful body that closes beyond the swept level and beyond the sweep candle close.
4. **Stop:** beyond the sweep wick (the pain-point extreme).
5. **Target 1:** +5 points, exit 50 lots.
6. **Target 2:** +15 points, exit the remaining 50 lots.

If any of those conditions are missing, there is no trade.

## Setup

```bash
cd liquidity-sweep-trap
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Delta Exchange settings
```

## Run Backtest (CLI)

```bash
python main.py --days 30
```

## Run Streamlit UI

```bash
streamlit run app.py
```

The dashboard includes:

- Sidebar settings (symbol, days, wallet, exchange, 15m or 1h analysis)
- Overview with metrics and price chart
- Rules, results, trade charts, trade log, and downloadable report

Options:

| Flag | Description |
|------|-------------|
| `--symbol ETHUSD` | Trading pair |
| `--days 30` | Backtest period (max 365) |
| `--starting-wallet 10000` | Simulated starting balance |
| `--base-url` | Delta Exchange API URL |
| `--skip-download` | Use cached CSV in `data/ohlcv/` |

## Project Structure

```
liquidity-sweep-trap/
├── app.py                              # Streamlit dashboard
├── main.py                             # CLI backtest runner
├── data/
│   ├── strategies/
│   │   └── liquidity_sweep_trap_rules.json
│   ├── ohlcv/                          # Downloaded candle data
│   └── reports/                        # Generated reports
└── src/
    ├── config.py
    ├── data_fetcher.py                 # Delta Exchange OHLCV
    ├── liquidity.py                    # HTF liquidity levels
    ├── strategy.py                     # Sweep / trap / confirmation
    ├── backtest.py                     # Trade simulation
    ├── charts.py                       # SVG charts for Streamlit
    ├── pipeline.py                     # Shared backtest runner
    └── report.py                       # Markdown + JSON output
```

## Outputs

After a run:

- `data/reports/ETHUSD_liquidity_sweep_trap_report.md`
- `data/reports/ETHUSD_liquidity_sweep_trap_results.json`

Adjust parameters in `data/strategies/liquidity_sweep_trap_rules.json`.

---

_For research only. Past performance does not guarantee future results._
