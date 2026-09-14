from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.backtest import BacktestResult, backtest_rule
from src.config import (
    OHLCV_DIR,
    REPORTS_DIR,
    STRATEGIES_DIR,
    TRANSCRIPTS_DIR,
    ensure_data_dirs,
)
from src.delta_data import (
    DeltaExchangeClient,
    expected_1m_candles,
    save_ohlcv,
    trim_ohlcv_to_days,
)
from src.timezone import delta_candle_day
from src.report import generate_report, save_report, save_results_json
from src.rule_extractor import (
    TradingRule,
    extract_rules_from_transcript,
    rules_from_json,
    rules_to_json,
)
from src.youtube_transcript import extract_video_id, fetch_transcript_text


@dataclass
class PipelineResult:
    video_id: str
    video_url: str
    transcript: str
    rules: list[TradingRule]
    rules_json: str
    ohlcv: list[dict]
    base_url: str
    results: list[BacktestResult]
    report_content: str
    transcript_path: Path
    rules_path: Path
    ohlcv_path: Path
    report_path: Path
    results_path: Path
    backtest_days: int = 0
    intraday_ohlcv: list[dict] | None = None


def _clamp_backtest_days(days: int) -> int:
    return max(1, min(days, 365))


def _daily_rows_for_intraday(daily_rows: list[dict], intraday_rows: list[dict]) -> list[dict]:
    if not intraday_rows:
        return daily_rows
    last_day = delta_candle_day(intraday_rows[-1]["timestamp"])
    return [row for row in daily_rows if delta_candle_day(row["timestamp"]) <= last_day]


def _cached_strategy_text(rules: list[TradingRule]) -> str:
    """Build reportable text when only the application's cached rules exist."""
    sections = []
    for rule in rules:
        sections.extend(
            [
                rule.name,
                *rule.setup_rules,
                *rule.entry_rules,
                *rule.exit_rules,
                *rule.risk_rules,
            ]
        )
    return "\n".join(sections)


def run_pipeline(
    video_url: str,
    symbol: str = "ETHUSD",
    resolution: str = "1d",
    days: int = 30,
    base_url: str = "https://api.india.delta.exchange",
    languages: list[str] | None = None,
    starting_wallet_usd: float = 10_000,
    start_date: date | None = None,
    end_date: date | None = None,
) -> PipelineResult:
    ensure_data_dirs()
    languages = languages or ["en"]
    if start_date and end_date:
        if start_date > end_date:
            raise ValueError("Start date must be on or before end date.")
        days = (end_date - start_date).days + 1
        if days > 365:
            raise ValueError("Backtest date range cannot exceed 365 days.")
    backtest_days = _clamp_backtest_days(days)

    video_id = extract_video_id(video_url)
    if not video_id:
        raise ValueError(f"Invalid YouTube URL: {video_url}")
    transcript_path = TRANSCRIPTS_DIR / f"{video_id}.txt"
    rules_path = STRATEGIES_DIR / f"{video_id}_rules.json"

    # Prefer saved rules JSON so manual backtest tweaks (e.g. skip filters) stick
    # across Run Analysis. Fall back to transcript extraction when missing.
    if rules_path.exists():
        rules = rules_from_json(rules_path.read_text(encoding="utf-8"))
        if transcript_path.exists() and transcript_path.read_text(encoding="utf-8").strip():
            transcript_text = transcript_path.read_text(encoding="utf-8")
        else:
            transcript_text = _cached_strategy_text(rules)
    elif transcript_path.exists() and transcript_path.read_text(encoding="utf-8").strip():
        transcript_text = transcript_path.read_text(encoding="utf-8")
        rules = extract_rules_from_transcript(transcript_text)
    else:
        transcript_data = fetch_transcript_text(video_url, languages=languages)
        transcript_text = transcript_data["text"]
        transcript_path.write_text(transcript_text, encoding="utf-8")
        rules = extract_rules_from_transcript(transcript_text)

    if not rules:
        raise ValueError(
            "No supported trading techniques found in transcript. "
            "The video should mention MACD, moving average crossover, or breakout."
        )
    rules_json = rules_to_json(rules)
    rules_path.write_text(rules_json, encoding="utf-8")

    client = DeltaExchangeClient(base_url=base_url)
    has_liquidity = any(rule.strategy_type == "liquidity" for rule in rules)

    # Extra daily candle so day 1 intraday has a previous-day high/low line.
    daily_days = backtest_days + 1 if has_liquidity else backtest_days
    daily_start_date = (
        start_date - timedelta(days=1)
        if start_date and has_liquidity
        else start_date
    )
    ohlcv = client.fetch_historical_ohlcv(
        symbol=symbol,
        resolution=resolution,
        days=daily_days,
        start_date=daily_start_date,
        end_date=end_date,
    )
    ohlcv_path = OHLCV_DIR / f"{symbol}_{resolution}.csv"
    save_ohlcv(ohlcv, str(ohlcv_path))

    intraday_rows: list[dict] | None = None
    if has_liquidity:
        intraday_rows = client.fetch_historical_ohlcv(
            symbol=symbol,
            resolution="1m",
            days=backtest_days,
            start_date=start_date,
            end_date=end_date,
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
        video_url=video_url,
        transcript=transcript_text,
        rules_json=rules_json,
        results=results,
        symbol=symbol,
        resolution=resolution,
        base_url=base_url,
    )
    report_path = REPORTS_DIR / f"{video_id}_report.md"
    results_path = REPORTS_DIR / f"{video_id}_results.json"
    save_report(report_content, report_path)
    save_results_json(results, results_path)

    return PipelineResult(
        video_id=video_id,
        video_url=video_url,
        transcript=transcript_text,
        rules=rules,
        rules_json=rules_json,
        ohlcv=ohlcv,
        base_url=base_url,
        results=results,
        report_content=report_content,
        transcript_path=transcript_path,
        rules_path=rules_path,
        ohlcv_path=ohlcv_path,
        report_path=report_path,
        results_path=results_path,
        backtest_days=backtest_days,
        intraday_ohlcv=intraday_rows,
    )
