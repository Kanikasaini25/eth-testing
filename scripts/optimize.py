"""Coordinate search over strategy parameters on cached India-live candles.

Optimises risk-adjusted return with a hard floor on the per-setup win rate, then
reports the winner on a held-out tail the search never saw.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from multiprocessing import Pool
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from scripts.cache_history import load_cached
from src.backtest import BacktestParams, run_liquidity_backtest
from src.timezone import ist_display

# Realistic Delta India costs, held fixed so the search cannot buy results with fees.
COST_DEFAULTS = dict(
    fee_pct_per_side=0.05,
    fee_maker_pct=0.02,
    maker_on_take_profit=True,
    maker_on_entry=False,
    scalper_offer=True,
    gst_pct=0.0,
    starting_wallet_usd=10000.0,
)

SEARCH_SPACE: dict[str, list] = {
    "target_points": [8, 10, 12, 15, 18, 20, 25, 30, 35, 40],
    "runner_target_points": [0, 30, 45, 60, 90, 120],
    "partial_exit_pct": [0, 50, 60, 70, 80],
    "breakeven_points": [0, 4, 6, 8, 10, 12, 15, 20],
    "max_sl_points": [8, 10, 12, 15, 18, 22, 26, 30, 35],
    "sl_buffer_points": [0.5, 1.0, 2.0, 3.0],
    "min_sweep_points": [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0],
    "min_confirm_body": [0.0, 0.5, 1.0, 1.5, 2.0, 2.5],
    "confirm_timeout_minutes": [15, 30, 45, 60, 90, 120],
    "max_hold_minutes": [0, 29, 60, 120, 240],
    "swing_left": [1, 2, 3, 4],
    "swing_right": [1, 2, 3, 4],
    "swing_lookback": [12, 24, 48, 96],
    "require_close_break": [False, True],
    "one_shot_confirm": [False, True],
    "require_reclaim": [True, False],
    "require_close_back": [True, False],
}

# name -> (min per-fold setups, min per-setup win rate)
PROFILES: dict[str, tuple[int, float]] = {
    "winrate": (10, 0.85),
    "balanced": (12, 0.70),
    "profit": (12, 0.55),
}

_GATE: tuple[int, float] = PROFILES["balanced"]

# 15m rows are always passed whole so swings stay warmed up; only 1m is sliced.
_M15: list[dict] = []
_FOLDS: list[list[dict]] = []


def split_history(
    m15: list[dict], m1: list[dict], train_frac: float
) -> tuple[list[dict], list[dict]]:
    cut = int(len(m1) * train_frac)
    return m1[:cut], m1[cut:]


def make_folds(m1_train: list[dict], n_folds: int) -> list[list[dict]]:
    size = len(m1_train) // n_folds
    return [
        m1_train[i * size : (i + 1) * size if i < n_folds - 1 else len(m1_train)]
        for i in range(n_folds)
    ]


def setup_metrics(trades: list[dict], starting_wallet: float) -> dict:
    """Collapse scale-out fills back into one round trip per entry."""
    setups: dict[tuple[str, str], float] = {}
    order: list[tuple[str, str]] = []
    for trade in trades:
        key = (trade["entry_ts"], trade["side"])
        if key not in setups:
            setups[key] = 0.0
            order.append(key)
        setups[key] += float(trade["net_usd"])

    gross = sum(float(t.get("gross_usd") or 0.0) for t in trades)
    fees = sum(float(t.get("fee_usd") or 0.0) for t in trades)
    nets = [setups[key] for key in order]
    if not nets:
        return {
            "setups": 0,
            "fills": 0,
            "win_rate": 0.0,
            "net_pnl": 0.0,
            "gross": 0.0,
            "fees": 0.0,
            "profit_factor": 0.0,
            "max_dd": 0.0,
            "expectancy": 0.0,
            "calmar": 0.0,
        }

    wins = [n for n in nets if n > 0]
    losses = [n for n in nets if n <= 0]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    wallet = starting_wallet
    peak = starting_wallet
    max_dd = 0.0
    for net in nets:
        wallet += net
        peak = max(peak, wallet)
        max_dd = max(max_dd, peak - wallet)
    net_pnl = wallet - starting_wallet
    return {
        "setups": len(nets),
        "fills": len(trades),
        "win_rate": len(wins) / len(nets),
        "net_pnl": net_pnl,
        "gross": gross,
        "fees": fees,
        "profit_factor": (gross_win / gross_loss) if gross_loss else (999.0 if gross_win else 0.0),
        "max_dd": max_dd,
        "expectancy": net_pnl / len(nets),
        "calmar": net_pnl / max_dd if max_dd > 0 else net_pnl,
    }


def evaluate(params: BacktestParams, m15: list[dict], m1: list[dict]) -> dict:
    result = run_liquidity_backtest(m15, m1, params)
    metrics = setup_metrics(result.trades, params.starting_wallet_usd)
    metrics["grabs"] = result.grab_count
    return metrics


def evaluate_folds(params: BacktestParams, m15: list[dict], folds: list[list[dict]]) -> dict:
    """Aggregate across time folds so a config has to work in more than one regime."""
    per_fold = [evaluate(params, m15, fold) for fold in folds]
    total_setups = sum(f["setups"] for f in per_fold)
    total_pnl = sum(f["net_pnl"] for f in per_fold)
    wins = sum(f["win_rate"] * f["setups"] for f in per_fold)
    worst_dd = max((f["max_dd"] for f in per_fold), default=0.0)
    profitable = sum(1 for f in per_fold if f["net_pnl"] > 0)
    return {
        "setups": total_setups,
        "fills": sum(f["fills"] for f in per_fold),
        "win_rate": wins / total_setups if total_setups else 0.0,
        "net_pnl": total_pnl,
        "gross": sum(f["gross"] for f in per_fold),
        "fees": sum(f["fees"] for f in per_fold),
        "profit_factor": min(f["profit_factor"] for f in per_fold) if per_fold else 0.0,
        "max_dd": worst_dd,
        "expectancy": total_pnl / total_setups if total_setups else 0.0,
        "calmar": total_pnl / worst_dd if worst_dd > 0 else total_pnl,
        "folds_profitable": profitable,
        "folds": len(per_fold),
        "min_fold_setups": min((f["setups"] for f in per_fold), default=0),
        "worst_fold_pnl": min((f["net_pnl"] for f in per_fold), default=0.0),
    }


def score(metrics: dict) -> float:
    """Profit penalised by risk, gated on being active, accurate, and consistent."""
    min_setups, min_win = _GATE
    if metrics["min_fold_setups"] < min_setups:
        return -1e9 + metrics["min_fold_setups"]
    if metrics["win_rate"] < min_win:
        return -1e8 + metrics["win_rate"] * 1e6
    if metrics["net_pnl"] <= 0:
        return -1e7 + metrics["net_pnl"]
    consistency = metrics["folds_profitable"] / metrics["folds"]
    # sqrt keeps drawdown meaningful without letting a 2-trade config win on a zero DD
    return metrics["net_pnl"] / max(metrics["max_dd"], 5.0) ** 0.5 * consistency**2


def _init_pool(m15: list[dict], folds: list[list[dict]], gate: tuple[int, float]) -> None:
    global _M15, _FOLDS, _GATE
    _M15, _FOLDS, _GATE = m15, folds, gate


def _score_candidate(payload: tuple[str, object, dict]) -> tuple[str, object, float, dict]:
    name, value, base = payload
    params = BacktestParams(**{**base, name: value})
    metrics = evaluate_folds(params, _M15, _FOLDS)
    return name, value, score(metrics), metrics


def coordinate_search(
    base: BacktestParams,
    m15: list[dict],
    folds: list[list[dict]],
    passes: int,
    workers: int,
) -> tuple[BacktestParams, dict]:
    current = asdict(base)
    best_metrics = evaluate_folds(BacktestParams(**current), m15, folds)
    best_score = score(best_metrics)
    print(f"baseline  score={best_score:9.3f}  {fmt(best_metrics)}", flush=True)

    with Pool(workers, initializer=_init_pool, initargs=(m15, folds, _GATE)) as pool:
        for round_no in range(1, passes + 1):
            improved = False
            for name, options in SEARCH_SPACE.items():
                jobs = [
                    (name, value, dict(current))
                    for value in options
                    if value != current[name]
                ]
                if not jobs:
                    continue
                changed = False
                for cand_name, value, cand_score, metrics in pool.imap_unordered(
                    _score_candidate, jobs
                ):
                    if cand_score > best_score + 1e-9:
                        best_score = cand_score
                        best_metrics = metrics
                        current[cand_name] = value
                        improved = changed = True
                if changed:
                    print(
                        f"  pass {round_no} {name:26s} -> {current[name]!r:8}  "
                        f"score={best_score:9.3f}  {fmt(best_metrics)}",
                        flush=True,
                    )
            if not improved:
                print(f"pass {round_no}: no further improvement", flush=True)
                break
    return BacktestParams(**current), best_metrics


def fmt(m: dict) -> str:
    text = (
        f"setups={m['setups']:3d} win={m['win_rate']*100:5.1f}% "
        f"pnl=${m['net_pnl']:9.2f} pf={m['profit_factor']:5.2f} "
        f"dd=${m['max_dd']:7.2f} exp=${m['expectancy']:6.2f}"
    )
    if "folds" in m:
        text += f" folds+={m['folds_profitable']}/{m['folds']}"
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="ETHUSD")
    parser.add_argument("--train-frac", type=float, default=0.7)
    parser.add_argument("--folds", type=int, default=4)
    parser.add_argument("--passes", type=int, default=4)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--lots", type=int, default=100)
    parser.add_argument("--profile", choices=sorted(PROFILES), default="balanced")
    parser.add_argument("--out", default="data/best_params.json")
    args = parser.parse_args()

    global _GATE
    _GATE = PROFILES[args.profile]
    print(f"profile: {args.profile}  (min {_GATE[0]} setups/fold, win rate >= {_GATE[1]:.0%})")

    m15 = load_cached(args.symbol, "15m")
    m1 = load_cached(args.symbol, "1m")
    print(
        f"history: {len(m15)} x 15m, {len(m1)} x 1m  "
        f"{ist_display(m1[0]['timestamp'])} -> {ist_display(m1[-1]['timestamp'])} IST"
    )

    m1_tr, m1_te = split_history(m15, m1, args.train_frac)
    folds = make_folds(m1_tr, args.folds)
    print(
        f"train: {ist_display(m1_tr[0]['timestamp'])} -> {ist_display(m1_tr[-1]['timestamp'])} "
        f"({args.folds} folds)"
    )
    if m1_te:
        print(
            f"test : {ist_display(m1_te[0]['timestamp'])} -> "
            f"{ist_display(m1_te[-1]['timestamp'])} (never seen by the search)"
        )
    else:
        print("test : none — folds cover the whole history")
    print()

    base = BacktestParams(position_lots=args.lots, **COST_DEFAULTS)
    best, train_metrics = coordinate_search(base, m15, folds, args.passes, args.workers)

    print("\n=== best config ===")
    for key, value in asdict(best).items():
        if key not in COST_DEFAULTS and key != "usd_per_point_per_lot":
            print(f"  {key:26s} {value}")

    baseline = BacktestParams(position_lots=args.lots, **COST_DEFAULTS)
    print(f"\ntrain folds  {fmt(train_metrics)}")
    for index, fold in enumerate(folds, 1):
        print(f"  fold {index}      {fmt(evaluate(best, m15, fold))}")
    if m1_te:
        print(f"HOLD-OUT     {fmt(evaluate(best, m15, m1_te))}")
    print(f"full 180d    {fmt(evaluate(best, m15, m1))}")
    print(f"\nold defaults full 180d  {fmt(evaluate(baseline, m15, m1))}")
    if m1_te:
        print(f"old defaults hold-out   {fmt(evaluate(baseline, m15, m1_te))}")

    out = PROJECT_DIR / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(asdict(best), indent=2))
    print(f"\nsaved -> {out}")


if __name__ == "__main__":
    main()
