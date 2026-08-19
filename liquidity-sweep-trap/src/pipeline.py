from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.backtest import BacktestResult, backtest_liquidity_sweep_trap
from src.config import OHLCV_DIR, REPORTS_DIR, STRATEGIES_DIR, ensure_data_dirs
from src.data_fetcher import (
    DeltaExchangeClient,
    expected_candles,
    load_ohlcv,
    resolution_from_minutes,
    save_ohlcv,
    trim_ohlcv_to_days,
)
from src.report import generate_report, save_report, save_results_json


@dataclass
class PipelineResult:
    symbol: str
    days: int
    candles: list[dict]
    rule: dict
    result: BacktestResult
    report_content: str
    rules_json: str
    ohlcv_path: Path
    report_path: Path
    results_path: Path
    entry_resolution: str
    analysis_tf_minutes: int


def default_rules_path() -> Path:
    return STRATEGIES_DIR / "liquidity_sweep_trap_rules.json"


def run_backtest(
    *,
    symbol: str,
    days: int,
    starting_wallet_usd: float,
    base_url: str,
    rules_path: Path | None = None,
    skip_download: bool = False,
    save_outputs: bool = True,
    parameter_overrides: dict | None = None,
) -> PipelineResult:
    ensure_data_dirs()

    rules_file = rules_path or default_rules_path()
    if not rules_file.exists():
        raise FileNotFoundError(f"Rules file not found: {rules_file}")

    rules = json.loads(rules_file.read_text(encoding="utf-8"))
    if not rules:
        raise ValueError("Rules file is empty")

    rule = rules[0]
    rule["parameters"]["starting_wallet_usd"] = starting_wallet_usd
    if parameter_overrides:
        rule["parameters"].update(parameter_overrides)

    entry_minutes = int(rule["parameters"].get("entry_tf_minutes", 1))
    analysis_minutes = int(rule["parameters"].get("analysis_tf_minutes", 15))
    entry_resolution = resolution_from_minutes(entry_minutes)
    rules_json = json.dumps(rules, indent=2)

    ohlcv_path = OHLCV_DIR / f"{symbol}_{entry_resolution}.csv"
    required_candles = expected_candles(days, entry_resolution)

    if skip_download and ohlcv_path.exists():
        candles = load_ohlcv(ohlcv_path)
        if len(candles) < required_candles:
            client = DeltaExchangeClient(base_url=base_url)
            candles = client.fetch_historical_ohlcv(symbol, entry_resolution, days)
            save_ohlcv(candles, ohlcv_path)
        else:
            candles = trim_ohlcv_to_days(candles, days, entry_resolution)
    else:
        client = DeltaExchangeClient(base_url=base_url)
        candles = client.fetch_historical_ohlcv(symbol, entry_resolution, days)
        save_ohlcv(candles, ohlcv_path)
        candles = trim_ohlcv_to_days(candles, days, entry_resolution)

    result = backtest_liquidity_sweep_trap(candles, rule)
    report_content = generate_report(rules_json, [result], symbol, days, analysis_minutes, entry_resolution)

    report_path = REPORTS_DIR / f"{symbol}_liquidity_sweep_trap_report.md"
    results_path = REPORTS_DIR / f"{symbol}_liquidity_sweep_trap_results.json"

    if save_outputs:
        save_report(report_content, report_path)
        save_results_json([result], results_path)

    return PipelineResult(
        symbol=symbol,
        days=days,
        candles=candles,
        rule=rule,
        result=result,
        report_content=report_content,
        rules_json=rules_json,
        ohlcv_path=ohlcv_path,
        report_path=report_path,
        results_path=results_path,
        entry_resolution=entry_resolution,
        analysis_tf_minutes=analysis_minutes,
    )
