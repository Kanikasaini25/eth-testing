#!/usr/bin/env python3
"""Find higher-frequency / smaller-profit configs vs the selective $353 setup."""

from __future__ import annotations

import json
import pickle
import sys
from copy import deepcopy
from itertools import product
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

from src.backtest import run_pattern_backtest
from src.product_specs import backtest_params_from_env

CACHE = PROJECT_DIR / "data" / "opt_candles.pkl"
OUT = PROJECT_DIR / "data" / "freq_best.json"


def main() -> None:
    blob = pickle.load(CACHE.open("rb"))
    sig, m1 = blob["sig"], blob["m1"]
    base = backtest_params_from_env("PAXGUSD")

    rows: list[dict] = []
    combos = list(
        product(
            [1, 2],
            [2.2, 2.5],
            [1.5, 2.0],
            [20, 25, 28],
            [22, 25],
            [1.0, 1.2],
            [10, 12],
            [(40.0, 30.0, 20.0, 5.0), (45.0, 30.0, 15.0, 5.0), (50.0, 25.0, 15.0, 5.0)],
        )
    )
    print(f"Testing {len(combos)} configs…", flush=True)
    for i, (votes, shadow, pat, t, max_sl, rr, be, scale) in enumerate(combos, 1):
        ov = dict(
            min_overlay_votes=votes,
            min_shadow_ratio=float(shadow),
            min_pattern_points=float(pat),
            target_points=float(t),
            max_sl_points=float(max_sl),
            min_rr_ratio=float(rr),
            breakeven_points=float(be),
            exit_scale_pcts=scale,
            partial_exit_pct=float(scale[0]),
            position_lots=3000,
            use_session_filter=False,
        )
        params = deepcopy(base)
        for k, v in ov.items():
            setattr(params, k, v)
        result = run_pattern_backtest(sig, m1, params, bar_seconds=900)
        rows.append(
            {
                "net": float(result.net_pnl),
                "wr": round(result.win_rate * 100, 1),
                "tr": int(result.trade_count),
                "sl": int(result.sl_count),
                "slpct": round(100.0 * result.sl_count / max(result.trade_count, 1), 1),
                "avg": round(float(result.net_pnl) / max(result.trade_count, 1), 2),
                "votes": votes,
                "shadow": shadow,
                "pat": pat,
                "t": t,
                "max_sl": max_sl,
                "rr": rr,
                "be": be,
                "scale": list(scale),
            }
        )
        if i % 50 == 0:
            print(f"  …{i}/{len(combos)}", flush=True)

    picks = [
        r
        for r in rows
        if r["net"] >= 300 and r["tr"] >= 24 and r["wr"] >= 60 and r["slpct"] <= 40
    ]
    picks.sort(key=lambda x: (-x["tr"], -x["net"], -x["wr"]))
    print("\nPICK ≥$300 tr≥24 WR≥60 SL%≤40:", flush=True)
    for i, x in enumerate(picks[:10], 1):
        print(
            f"{i:2}. tr={x['tr']} net=${x['net']:.2f} avg=${x['avg']:.2f} "
            f"wr={x['wr']}% sl%={x['slpct']} T={x['t']} v={x['votes']} "
            f"sh={x['shadow']} pat={x['pat']} rr={x['rr']} be={x['be']} "
            f"maxSL={x['max_sl']} scale={x['scale']}",
            flush=True,
        )
    if not picks:
        picks = [r for r in rows if r["net"] >= 280 and r["tr"] >= 24]
        picks.sort(key=lambda x: (-x["tr"], -x["net"]))
        print("\nFALLBACK ≥$280 tr≥24:", flush=True)
        for i, x in enumerate(picks[:8], 1):
            print(
                f"{i:2}. tr={x['tr']} net=${x['net']:.2f} avg=${x['avg']:.2f} "
                f"wr={x['wr']}% T={x['t']} v={x['votes']} sh={x['shadow']} scale={x['scale']}",
                flush=True,
            )
    if picks:
        OUT.write_text(json.dumps(picks[0], indent=2))
        print(f"\nSaved {OUT}", flush=True)


if __name__ == "__main__":
    main()
