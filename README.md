# YouTube Strategy Backtester

Analyze trading techniques from YouTube tutorials and backtest them on **Delta Exchange ETH futures** historical data.

## What it does

1. Fetches YouTube video transcript
2. Extracts trading techniques (MACD, MA crossover, breakout)
3. Downloads **ETHUSD 1d** candles from Delta Exchange
4. Backtests each technique on historical data
5. Saves a markdown report + JSON results

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your YouTube URL:

```env
YOUTUBE_URLS=https://www.youtube.com/watch?v=your-video-id
DELTA_SYMBOL=ETHUSD
DELTA_RESOLUTION=1d
BACKTEST_DAYS=730
```

## Run with Streamlit UI

```bash
streamlit run app.py
```

Open the app in your browser, enter a YouTube URL, and click **Run Analysis**.

## Run full pipeline (CLI)

```bash
python main.py
```

Or with options:

```bash
python main.py --url "https://youtube.com/watch?v=..." --symbol ETHUSD --days 365
```

## Output

| File | Description |
|------|-------------|
| `data/transcripts/{video_id}.txt` | Raw transcript |
| `data/strategies/{video_id}_rules.json` | Extracted techniques |
| `data/ohlcv/ETHUSD_1d.csv` | Delta Exchange candle data |
| `data/reports/{video_id}_report.md` | Backtest report |
| `data/reports/{video_id}_results.json` | Raw backtest metrics |

## Transcript-only (legacy)

```bash
python extract_transcripts.py
```

## Supported techniques

| Detected in transcript | Strategy |
|------------------------|----------|
| Golden cross / MA cross | Moving average crossover |
| MACD | MACD signal crossover |
| Breakout / resistance | Price breakout |

If no clear rules are found, the pipeline stops with an error.

## Delta Exchange

- **India:** `https://api.india.delta.exchange` → symbol `ETHUSD`
- **Global:** `https://api.delta.exchange` → symbol `ETHUSDT`

No API key required for historical candle data.

## Disclaimer

For research and education only. Past performance does not guarantee future results.
