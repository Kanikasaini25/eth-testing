#!/usr/bin/env python3
"""Continuous random + staged search for higher net USD / lower SL damage.

Runs until interrupted. Goal: find configs with net ≈ $280–300+ on 30d PAXGUSD.
"""

from __future__ import annotations

import json
import pickle
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

# Unbuffered progress when run in background / redirected stdout
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from src.backtest import BacktestParams, run_pattern_backtest
from src.config import get_candle_base_url
from src.delta_data import DeltaExchangeClient
from src.product_specs import backtest_params_from_env

CACHE = PROJECT_DIR / "data" / "opt_candles.pkl"
OUT = PROJECT_DIR / "data" / "opt_results.json"
TARGET_NET = 280.0


def load_candles(days: int = 30):
    if CACHE.exists():
        blob = pickle.load(CACHE.open("rb"))
        if blob.get("days") == days and blob.get("sig") and blob.get("m1"):
            print(f"Using cached {days}d candles")
            return blob["sig"], blob["m1"]
    client = DeltaExchangeClient(base_url=get_candle_base_url())
    end = int(time.time())
    start = end - days * 86400
    print(f"Fetching {days}d PAXGUSD India LIVE…")
    sig = client.fetch_historical_ohlcv_range("PAXGUSD", "15m", start, end)
    m1 = client.fetch_historical_ohlcv_range("PAXGUSD", "1m", start, end)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    pickle.dump({"days": days, "sig": sig, "m1": m1}, CACHE.open("wb"))
    return sig, m1


def sample_overrides(rng: random.Random) -> dict:
    scales = [
        (30.0, 40.0, 10.0, 10.0),
        (40.0, 30.0, 10.0, 10.0),
        (50.0, 20.0, 15.0, 5.0),
        (25.0, 25.0, 20.0, 15.0),
        (35.0, 35.0, 15.0, 5.0),
        (45.0, 25.0, 15.0, 5.0),
        (20.0, 30.0, 20.0, 15.0),
        (60.0, 20.0, 10.0, 5.0),
        (15.0, 25.0, 25.0, 15.0),
        (30.0, 30.0, 20.0, 10.0),
    ]
    scale = rng.choice(scales)
    return {
        "position_lots": rng.choice([1000, 1200, 1500, 1800, 2000, 2200, 2500, 2800, 3000]),
        "target_points": float(rng.choice([25, 30, 35, 40, 45, 50, 55, 60, 70, 80])),
        "breakeven_points": float(rng.choice([5, 8, 10, 12, 15, 18, 20, 25])),
        "max_sl_points": float(rng.choice([12, 15, 18, 20, 22, 25, 30])),
        "min_rr_ratio": float(rng.choice([1.0, 1.2, 1.5, 1.8, 2.0, 2.5])),
        "min_overlay_votes": int(rng.choice([1, 2, 3])),
        "atr_target_mult": float(rng.choice([1.2, 1.5, 2.0, 2.5, 3.0, 3.5])),
        "atr_max_risk_mult": float(rng.choice([1.2, 1.5, 2.0, 2.5])),
        "exit_scale_pcts": scale,
        "partial_exit_pct": float(scale[0]),
        "max_targets": 5,
        "min_shadow_ratio": float(rng.choice([2.0, 2.2, 2.5, 2.8, 3.0])),
        "min_pattern_points": float(rng.choice([1.5, 2.0, 2.5, 3.0])),
        "use_session_filter": rng.choice([True, False]),
        "use_bollinger_rsi": rng.choice([True, False]),
        "use_ema_regime": rng.choice([True, False]),
        "use_adx_filter": rng.choice([True, False]),
        "use_donchian_filter": rng.choice([True, False]),
        "use_adaptive_targets": True,
        "use_atr_stops": True,
        "adx_min": float(rng.choice([15, 18, 20, 22, 25])),
    }


def refine_around(best: dict, rng: random.Random) -> dict:
    """Local search near a strong config."""
    base = {
        "position_lots": best["lots"],
        "target_points": best["target_points"],
        "breakeven_points": best["breakeven"],
        "max_sl_points": best["max_sl"],
        "min_rr_ratio": best["min_rr"],
        "min_overlay_votes": best["votes"],
        "atr_target_mult": best["atr_target_mult"],
        "atr_max_risk_mult": best["atr_max_risk_mult"],
        "exit_scale_pcts": tuple(best["exit_scale_pcts"]),
        "partial_exit_pct": float(best["exit_scale_pcts"][0]),
        "max_targets": 5,
        "min_shadow_ratio": best["min_shadow_ratio"],
        "use_session_filter": best["use_session_filter"],
        "use_bollinger_rsi": best["use_bollinger_rsi"],
        "use_adaptive_targets": True,
        "use_atr_stops": True,
    }
    # jitter
    # Cap lots so search improves edge, not just leverage
    base["position_lots"] = min(3000, max(800, int(base["position_lots"] + rng.choice([-300, -200, -100, 0, 100, 200, 300]))))
    base["target_points"] = max(20.0, float(base["target_points"] + rng.choice([-10, -5, 0, 5, 10, 15])))
    base["breakeven_points"] = max(0.0, float(base["breakeven_points"] + rng.choice([-5, -2, 0, 2, 5])))
    base["max_sl_points"] = max(10.0, float(base["max_sl_points"] + rng.choice([-5, -2, 0, 2, 5])))
    return base


def run_one(sig, m1, base: BacktestParams, overrides: dict):
    params = deepcopy(base)
    for k, v in overrides.items():
        setattr(params, k, v)
    result = run_pattern_backtest(sig, m1, params, bar_seconds=900)
    return params, result


def summarize(params: BacktestParams, result) -> dict:
    trades = max(int(result.trade_count), 1)
    return {
        "net_pnl": float(result.net_pnl),
        "trades": int(result.trade_count),
        "win_rate": round(float(result.win_rate) * 100, 1),
        "tp": int(result.tp_count),
        "sl": int(result.sl_count),
        "sl_pct": round(100.0 * float(result.sl_count) / trades, 1),
        "max_dd": float(result.max_drawdown),
        "lots": int(params.position_lots),
        "target_points": float(params.target_points),
        "breakeven": float(params.breakeven_points),
        "max_sl": float(params.max_sl_points),
        "min_rr": float(params.min_rr_ratio),
        "votes": int(params.min_overlay_votes),
        "atr_target_mult": float(params.atr_target_mult),
        "atr_max_risk_mult": float(params.atr_max_risk_mult),
        "exit_scale_pcts": list(params.exit_scale_pcts),
        "min_shadow_ratio": float(params.min_shadow_ratio),
        "use_session_filter": bool(params.use_session_filter),
        "use_bollinger_rsi": bool(params.use_bollinger_rsi),
        "use_ema_regime": bool(params.use_ema_regime),
        "use_adx_filter": bool(params.use_adx_filter),
        "use_donchian_filter": bool(params.use_donchian_filter),
        "adx_min": float(params.adx_min),
    }


def main() -> None:
    rng = random.Random(42)
    sig, m1 = load_candles(30)
    base = backtest_params_from_env("PAXGUSD")
    best: list[dict] = []
    seen = 0
    hits = 0
    t0 = time.time()
    print(f"Continuous search · goal net ≥ ${TARGET_NET} · Ctrl+C to stop")
    print(f"Bars {len(sig)} 15m / {len(m1)} 1m · baseline lots={base.position_lots}")

    try:
        while True:
            if seen > 0 and seen % 40 == 0 and best:
                overrides = refine_around(best[0], rng)
            else:
                overrides = sample_overrides(rng)

            params, result = run_one(sig, m1, base, overrides)
            row = summarize(params, result)
            seen += 1
            best.append(row)
            best.sort(key=lambda r: (r["net_pnl"], r["win_rate"], -r["sl_pct"]), reverse=True)
            best = best[:40]

            if row["net_pnl"] >= TARGET_NET:
                hits += 1
                print(
                    f"★ HIT #{hits} net=${row['net_pnl']:.2f} wr={row['win_rate']}% "
                    f"sl%={row['sl_pct']} trades={row['trades']} lots={row['lots']} "
                    f"T={row['target_points']} BE={row['breakeven']} scale={row['exit_scale_pcts']}"
                )

            if seen % 20 == 0:
                top = best[0]
                print(
                    f"[{seen}] {time.time()-t0:.0f}s top=${top['net_pnl']:.2f} "
                    f"wr={top['win_rate']}% sl%={top['sl_pct']} lots={top['lots']} "
                    f"T={top['target_points']} hits={hits}"
                )
                OUT.write_text(json.dumps({"seen": seen, "hits": hits, "top": best}, indent=2))

            # Keep going — user asked not to stop. Soft milestone logging only.
            if hits >= 20 and seen >= 500:
                # Reload slightly longer window once and continue
                pass
    except KeyboardInterrupt:
        print("\nStopped.")

    OUT.write_text(json.dumps({"seen": seen, "hits": hits, "top": best}, indent=2))
    print("\n=== TOP 15 ===")
    for i, row in enumerate(best[:15], 1):
        print(
            f"{i:2}. ${row['net_pnl']:7.2f} wr={row['win_rate']:5.1f}% "
            f"sl%={row['sl_pct']:5.1f} tr={row['trades']:3} lots={row['lots']} "
            f"T={row['target_points']} BE={row['breakeven']} "
            f"scale={row['exit_scale_pcts']} votes={row['votes']} sess={row['use_session_filter']}"
        )
    print(f"Saved {OUT}")


if __name__ == "__main__":
    main()
