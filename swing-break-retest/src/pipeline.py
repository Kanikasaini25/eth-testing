from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from src.backtest import BacktestResult, backtest_swing_break_retest
from src.config import OHLCV_DIR, REPORTS_DIR, STRATEGIES_DIR, ensure_data_dirs
from src.data_fetcher import (
    DeltaExchangeClient,
    expected_5m_candles,
    load_ohlcv,
    save_ohlcv,
    trim_ohlcv_to_days,
)
from src.report import generate_report, save_report, save_results_json


@dataclass
class PipelineResult:
    symbol: str
    days: int
    candles_5m: list[dict]
    rule: dict
    result: BacktestResult
    report_content: str
    rules_json: str
    ohlcv_path: Path
    report_path: Path
    results_path: Path


def default_rules_path() -> Path:
    return STRATEGIES_DIR / "swing_break_retest_rules.json"


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
    rules_json = rules_file.read_text(encoding="utf-8")

    ohlcv_path = OHLCV_DIR / f"{symbol}_5m.csv"
    required_candles = expected_5m_candles(days)

    if skip_download and ohlcv_path.exists():
        candles_5m = load_ohlcv(ohlcv_path)
        if len(candles_5m) < required_candles:
            client = DeltaExchangeClient(base_url=base_url)
            candles_5m = client.fetch_historical_ohlcv(symbol, "5m", days)
            save_ohlcv(candles_5m, ohlcv_path)
        else:
            candles_5m = trim_ohlcv_to_days(candles_5m, days, "5m")
    else:
        client = DeltaExchangeClient(base_url=base_url)
        candles_5m = client.fetch_historical_ohlcv(symbol, "5m", days)
        save_ohlcv(candles_5m, ohlcv_path)
        candles_5m = trim_ohlcv_to_days(candles_5m, days, "5m")

    result = backtest_swing_break_retest(candles_5m, rule)
    report_content = generate_report(rules_json, [result], symbol, days)

    report_path = REPORTS_DIR / f"{symbol}_swing_break_retest_report.md"
    results_path = REPORTS_DIR / f"{symbol}_swing_break_retest_results.json"

    if save_outputs:
        save_report(report_content, report_path)
        save_results_json([result], results_path)

    return PipelineResult(
        symbol=symbol,
        days=days,
        candles_5m=candles_5m,
        rule=rule,
        result=result,
        report_content=report_content,
        rules_json=rules_json,
        ohlcv_path=ohlcv_path,
        report_path=report_path,
        results_path=results_path,
    )
