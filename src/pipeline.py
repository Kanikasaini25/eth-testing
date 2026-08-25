from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.backtest import BacktestResult, Trade, backtest_rule
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


POC_STRATEGY_TYPES = {"m15_poc", "poc_value_area"}


def _is_poc_rule(rule: TradingRule) -> bool:
    return rule.strategy_type in POC_STRATEGY_TYPES


def _poc_to_backtest_result(rule: TradingRule, m15_rows: list[dict]) -> BacktestResult:
    from src.poc_backtest import params_from_rule, run_poc_backtest

    poc = run_poc_backtest(m15_rows, params_from_rule(rule.parameters))
    starting = poc.starting_wallet or float(rule.parameters.get("starting_wallet_usd", 10_000))
    trades: list[Trade] = []
    for item in poc.trades:
        entry = float(item["entry_price"])
        exit_px = float(item["exit_price"])
        if item["side"] == "long":
            return_pct = ((exit_px - entry) / entry) * 100 if entry else 0.0
        else:
            return_pct = ((entry - exit_px) / entry) * 100 if entry else 0.0
        trades.append(
            Trade(
                entry_date=item["entry_ts"],
                exit_date=item["exit_ts"],
                entry_price=entry,
                exit_price=exit_px,
                return_pct=round(return_pct, 4),
                exit_reason=item["reason"],
                side=item["side"],
                trade_type="Buy" if item["side"] == "long" else "Sell",
                entry_lots=int(item["lots"]),
                lots=int(item["lots"]),
                points=float(item["points"]),
                pnl_usd=float(item["net_usd"]),
                wallet_balance=float(item["wallet"]),
            )
        )

    first_close = float(m15_rows[0]["close"]) if m15_rows else 1.0
    last_close = float(m15_rows[-1]["close"]) if m15_rows else 1.0
    buy_hold = ((last_close - first_close) / first_close) * 100 if first_close else 0.0
    total_return = ((poc.ending_wallet - starting) / starting) * 100 if starting else 0.0
    win_rate = poc.win_rate * 100
    if not trades:
        verdict = "No trades generated"
    elif total_return > 0 and total_return > buy_hold and win_rate >= 50:
        verdict = "Works"
    elif total_return > buy_hold or total_return > 0 or win_rate >= 45:
        verdict = "Mixed"
    else:
        verdict = "Fails"

    avg_return = (
        sum(trade.return_pct for trade in trades) / len(trades) if trades else 0.0
    )
    return BacktestResult(
        rule_name=rule.name,
        strategy_type=rule.strategy_type,
        total_trades=len(trades),
        win_rate=round(win_rate, 2),
        total_return_pct=round(total_return, 2),
        buy_hold_return_pct=round(buy_hold, 2),
        max_drawdown_pct=round((poc.max_drawdown / starting) * 100, 2) if starting else 0.0,
        avg_return_pct=round(avg_return, 2),
        verdict=verdict,
        trades=trades,
        backtest_mode="15m_poc",
        rule_compliance={
            "uses_previous_day_poc": True,
            "uses_15m_reaction": True,
            "requires_return_to_poc": bool(rule.parameters.get("require_return", True)),
        },
    )


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
    has_poc = any(_is_poc_rule(rule) for rule in rules)

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
        save_ohlcv(intraday_rows, str(OHLCV_DIR / f"{symbol}_1m.csv"))

    m15_rows: list[dict] | None = None
    if has_poc:
        m15_days = backtest_days + 1
        m15_rows = client.fetch_historical_ohlcv(
            symbol=symbol,
            resolution="15m",
            days=m15_days,
        )
        save_ohlcv(m15_rows, str(OHLCV_DIR / f"{symbol}_15m.csv"))

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
        elif _is_poc_rule(rule) and m15_rows:
            results.append(_poc_to_backtest_result(rule, m15_rows))
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
        intraday_ohlcv=intraday_rows or m15_rows,
    )
