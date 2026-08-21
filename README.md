# LQDTY Live Strategy Bot

On the server:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Put Delta keys in `.env`. Keep `data/strategies/wI9b968AvW8_rules.json`.

```bash
python scripts/run_live_strategy.py --loop --enable
```

That command runs 24/7: fetches 1d/1m candles, places orders, optional email alerts.

For research only. Past performance does not guarantee future results.
