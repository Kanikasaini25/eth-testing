# 30M Swing Break + 5M Retest

Standalone backtesting project for the **Swing Break + Retest** strategy.

This folder is **independent** of the parent `youtube/` project — it does not import or reuse any code from there.

## Strategy Summary

| 30M Event | 5M Action | Trade |
|-----------|-----------|-------|
| Swing High breaks | Retest of Swing High | **LONG** |
| Swing Low breaks | Retest of Swing Low | **SHORT** |
| No break | Wait | **NO TRADE** |

**Concept:** Mark the 30-minute swing high and swing low. When either swing is broken, wait for price to retest the broken level on the 5-minute chart. Enter in the same direction as the breakout.

There is **no liquidity concept** in this setup.

## Setup

```bash
cd swing-break-retest
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

Opens a browser dashboard with:
- Sidebar settings (symbol, days, wallet, exchange)
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
swing-break-retest/
├── app.py                           # Streamlit dashboard
├── main.py                          # CLI backtest runner
├── data/
│   ├── strategies/
│   │   └── swing_break_retest_rules.json
│   ├── ohlcv/                       # Downloaded candle data
│   └── reports/                     # Generated reports
└── src/
    ├── config.py
    ├── data_fetcher.py              # Delta Exchange OHLCV
    ├── swing.py                     # 30M pivot swing detection
    ├── strategy.py                  # Break + retest logic
    ├── backtest.py                  # Trade simulation
    ├── charts.py                    # SVG charts for Streamlit
    ├── pipeline.py                  # Shared backtest runner
    └── report.py                    # Markdown + JSON output
```

## Outputs

After a run:

- `data/reports/ETHUSD_swing_break_retest_report.md` — human-readable report
- `data/reports/ETHUSD_swing_break_retest_results.json` — machine-readable results

## Exit Rules (Default)

- **Stop loss:** retest candle wick (low for longs, high for shorts)
- **Take profit:** 2:1 reward-to-risk

Adjust parameters in `data/strategies/swing_break_retest_rules.json`.

---

_For research only. Past performance does not guarantee future results._
