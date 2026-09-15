"""Re-price each preset under worse cost assumptions. A config that only survives the
best-case fee schedule is not tradeable."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scripts.cache_history import load_cached
from scripts.optimize import evaluate, split_history
from src.backtest import BacktestParams
from src.presets import STRATEGY

SCENARIOS: dict[str, dict] = {
    "modelled (scalper on, maker TP)": {},
    "no scalper offer": {"scalper_offer": False},
    "no scalper + taker exits": {"scalper_offer": False, "maker_on_take_profit": False},
    "worst fees + 18% GST": {
        "scalper_offer": False,
        "maker_on_take_profit": False,
        "gst_pct": 18.0,
    },
    "worst fees + 0.5pt slippage": {
        "scalper_offer": False,
        "maker_on_take_profit": False,
        "gst_pct": 18.0,
        "slippage_points": 0.5,
    },
    "worst fees + 1pt slippage": {
        "scalper_offer": False,
        "maker_on_take_profit": False,
        "gst_pct": 18.0,
        "slippage_points": 1.0,
    },
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSD")
    parser.add_argument("--train-frac", type=float, default=0.7)
    parser.add_argument("--params", help="optional JSON config; defaults to the tuned strategy")
    args = parser.parse_args()

    m15 = load_cached(args.symbol, "15m")
    m1 = load_cached(args.symbol, "1m")
    _train, hold = split_history(m15, m1, args.train_frac)

    base = STRATEGY
    if args.params:
        base = BacktestParams(**json.loads((PROJECT_DIR / args.params).read_text()))

    print(f"{'scenario':32s} {'setups':>7} {'win':>7} {'net PnL':>10} {'gross':>9} "
          f"{'fees':>9} {'PF':>6} {'maxDD':>8} {'per trade':>10} | hold-out")
    for label, overrides in SCENARIOS.items():
        params = replace(base, **overrides)
        full = evaluate(params, m15, m1)
        out = evaluate(params, m15, hold)
        print(
            f"{label:32s} {full['setups']:7d} {full['win_rate']*100:6.1f}% "
            f"${full['net_pnl']:9.2f} ${full['gross']:8.2f} ${full['fees']:8.2f} "
            f"{full['profit_factor']:6.2f} ${full['max_dd']:7.2f} "
            f"${full['expectancy']:9.2f} | ${out['net_pnl']:8.2f}"
        )


if __name__ == "__main__":
    main()
