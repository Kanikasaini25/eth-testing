"""Score candidate configs fold-by-fold over the whole cached history so consistency,
not one lucky stretch, decides which presets ship."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scripts.cache_history import load_cached
from scripts.optimize import evaluate, make_folds
from src.backtest import BacktestParams
from src.presets import STRATEGY
from src.timezone import ist_display

OLD_DEFAULTS = BacktestParams(
    target_points=30.0,
    swing_left=2,
    swing_right=2,
    swing_lookback=48,
    confirm_timeout_minutes=90,
    sl_buffer_points=1.0,
    max_sl_points=15.0,
    min_sweep_points=3.0,
    require_reclaim=True,
    partial_exit_pct=80.0,
    runner_target_points=90.0,
    fee_pct_per_side=0.05,
    fee_maker_pct=0.02,
    maker_on_take_profit=True,
    scalper_offer=True,
)


def candidates() -> dict[str, BacktestParams]:
    out = {"old defaults": OLD_DEFAULTS, "tuned strategy": STRATEGY}
    for path in sorted((PROJECT_DIR / "data").glob("wf_*.json")):
        out[f"6fold:{path.stem[3:]}"] = BacktestParams(**json.loads(path.read_text()))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSD")
    parser.add_argument("--folds", type=int, default=6)
    args = parser.parse_args()

    m15 = load_cached(args.symbol, "15m")
    m1 = load_cached(args.symbol, "1m")
    folds = make_folds(m1, args.folds)
    print(f"{args.folds} folds over {ist_display(m1[0]['timestamp'])} -> "
          f"{ist_display(m1[-1]['timestamp'])} IST\n")

    header = f"{'config':18s} {'n':>4} {'win':>6} {'netPnL':>9} {'PF':>5} {'maxDD':>7} {'Calmar':>7}  "
    header += " ".join(f"{'f' + str(i):>8}" for i in range(1, args.folds + 1))
    print(header)

    for name, params in candidates().items():
        full = evaluate(params, m15, m1)
        per_fold = [evaluate(params, m15, fold) for fold in folds]
        green = sum(1 for f in per_fold if f["net_pnl"] > 0)
        cells = " ".join(f"{f['net_pnl']:8.0f}" for f in per_fold)
        calmar = full["net_pnl"] / full["max_dd"] if full["max_dd"] else float("inf")
        print(
            f"{name:18s} {full['setups']:4d} {full['win_rate']*100:5.1f}% "
            f"${full['net_pnl']:8.2f} {full['profit_factor']:5.2f} ${full['max_dd']:6.2f} "
            f"{calmar:7.1f}  {cells}   {green}/{args.folds} green"
        )


if __name__ == "__main__":
    main()
