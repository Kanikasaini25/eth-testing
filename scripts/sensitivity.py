"""Perturb one parameter at a time around a config to see whether it sits on a plateau
or on a knife edge. A config that only works at exactly one value is overfit."""

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
from scripts.optimize import SEARCH_SPACE, evaluate, fmt, split_history
from src.backtest import BacktestParams
from src.presets import STRATEGY


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSD")
    parser.add_argument("--params", help="optional JSON config; defaults to the tuned strategy")
    parser.add_argument("--train-frac", type=float, default=0.7)
    args = parser.parse_args()

    best = STRATEGY
    if args.params:
        best = BacktestParams(**json.loads((PROJECT_DIR / args.params).read_text()))
    m15 = load_cached(args.symbol, "15m")
    m1 = load_cached(args.symbol, "1m")
    _m1_tr, m1_te = split_history(m15, m1, args.train_frac)

    print(f"BEST full   {fmt(evaluate(best, m15, m1))}")
    print(f"BEST hold   {fmt(evaluate(best, m15, m1_te))}\n")

    for name, options in SEARCH_SPACE.items():
        current = getattr(best, name)
        print(f"--- {name} (best = {current!r})")
        for value in options:
            trial = replace(best, **{name: value})
            full = evaluate(trial, m15, m1)
            hold = evaluate(trial, m15, m1_te)
            mark = " <=" if value == current else "   "
            print(
                f"  {value!r:>8}{mark}  full: pnl=${full['net_pnl']:8.2f} "
                f"win={full['win_rate']*100:5.1f}% n={full['setups']:3d} "
                f"dd=${full['max_dd']:6.2f} | hold: pnl=${hold['net_pnl']:8.2f} "
                f"win={hold['win_rate']*100:5.1f}% n={hold['setups']:3d}"
            )
        print()


if __name__ == "__main__":
    main()
