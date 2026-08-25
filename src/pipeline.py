from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.backtest import BacktestResult, backtest_rule
from src.config import (
    OHLCV_DIR,
    PROJECT_DIR,
    REPORTS_DIR,
    STRATEGIES_DIR,
    ensure_data_dirs,
)
from src.delta_data import (
    DeltaExchangeClient,
    save_ohlcv,
    trim_ohlcv_to_days,
)
from src.report import generate_report, save_report, save_results_json
from src.rule_extractor import TradingRule, load_rules, rules_to_json


@dataclass
class PipelineResult:
    strategy_id: str
    rules: list[TradingRule]
    rules_json: str
    ohlcv: list[dict]
    results: list[BacktestResult]
    report_content: str
    rules_path: Path
    ohlcv_path: Path
    report_path: Path
    results_path: Path
    backtest_days: int = 0
    intraday_ohlcv: list[dict] | None = None


def resolve_rules_path(rules_path: str | Path) -> Path:
    path = Path(rules_path)
    if path.exists():
        return path.resolve()
    candidates = [
        PROJECT_DIR / path,
        STRATEGIES_DIR / path,
        STRATEGIES_DIR / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    raise FileNotFoundError(f"Strategy rules not found: {rules_path}")


def _clamp_backtest_days(days: int) -> int:
    return max(1, min(days, 365))


def _daily_rows_for_intraday(daily_rows: list[dict], intraday_rows: list[dict]) -> list[dict]:
    if not intraday_rows:
        return daily_rows
    last_day = intraday_rows[-1]["timestamp"][:10]
    return [row for row in daily_rows if row["timestamp"][:10] <= last_day]


def run_pipeline(
    rules_path: str | Path,
    symbol: str = "ETHUSD",
    resolution: str = "1d",
    days: int = 30,
    base_url: str = "https://api.india.delta.exchange",
    starting_wallet_usd: float = 10_000,
) -> PipelineResult:
    ensure_data_dirs()
    backtest_days = _clamp_backtest_days(days)

    resolved_rules_path = resolve_rules_path(rules_path)
    rules = load_rules(resolved_rules_path)
    rules_json = rules_to_json(rules)
    strategy_id = resolved_rules_path.stem

    client = DeltaExchangeClient(base_url=base_url)
    has_liquidity = any(rule.strategy_type == "liquidity" for rule in rules)

    # Extra daily candle so day 1 intraday has a previous-day high/low line.
    daily_days = backtest_days + 1 if has_liquidity else backtest_days
    ohlcv = client.fetch_historical_ohlcv(symbol=symbol, resolution=resolution, days=daily_days)
    ohlcv_path = OHLCV_DIR / f"{symbol}_{resolution}.csv"
    save_ohlcv(ohlcv, str(ohlcv_path))

    intraday_rows: list[dict] | None = None
    if has_liquidity:
        intraday_rows = client.fetch_historical_ohlcv(
            symbol=symbol,
            resolution="1m",
            days=backtest_days,
        )
        intraday_rows = trim_ohlcv_to_days(intraday_rows, backtest_days, "1m")
        intraday_path = OHLCV_DIR / f"{symbol}_1m.csv"
        save_ohlcv(intraday_rows, str(intraday_path))

    daily_for_backtest = _daily_rows_for_intraday(ohlcv, intraday_rows or [])

    for rule in rules:
        rule.parameters["starting_wallet_usd"] = starting_wallet_usd

    results = []
    for rule in rules:
        if rule.strategy_type == "liquidity" and intraday_rows:
            results.append(
                backtest_rule(
                    ohlcv,
                    rule,
                    intraday_rows=intraday_rows,
                    daily_rows=daily_for_backtest,
                )
            )
        else:
            results.append(backtest_rule(ohlcv, rule))

    report_content = generate_report(
        strategy_id=strategy_id,
        rules_json=rules_json,
        results=results,
        symbol=symbol,
        resolution=resolution,
    )
    report_path = REPORTS_DIR / f"{strategy_id}_report.md"
    results_path = REPORTS_DIR / f"{strategy_id}_results.json"
    save_report(report_content, report_path)
    save_results_json(results, results_path)

    return PipelineResult(
        strategy_id=strategy_id,
        rules=rules,
        rules_json=rules_json,
        ohlcv=ohlcv,
        results=results,
        report_content=report_content,
        rules_path=resolved_rules_path,
        ohlcv_path=ohlcv_path,
        report_path=report_path,
        results_path=results_path,
        backtest_days=backtest_days,
        intraday_ohlcv=intraday_rows,
    )
