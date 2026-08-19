from __future__ import annotations

import json
from pathlib import Path

from src.backtest import BacktestResult, result_to_dict


def generate_report(
    rules_json: str,
    results: list[BacktestResult],
    symbol: str,
    days: int,
    analysis_tf_minutes: int,
    entry_resolution: str,
) -> str:
    lines = [
        "# Liquidity Sweep / Trap — Backtest Report",
        "",
        "## Strategy",
        "Find liquidity on the higher timeframe, wait for price to reach it, wait for the "
        "liquidity-taking / trap event, then enter only after confirmation. Target the next "
        "meaningful liquidity area. Do not enter on a simple touch.",
        "",
        "| Setup | Event | Trade |",
        "|-------|-------|-------|",
        "| Liquidity below | Sweep + trap + bullish confirmation | LONG |",
        "| Liquidity above | Sweep + trap + bearish confirmation | SHORT |",
        "| No sweep / no confirmation | Wait | NO TRADE |",
        "",
        "## Market Data",
        f"- Symbol: {symbol}",
        f"- Analysis timeframe: {analysis_tf_minutes}m",
        f"- Entry timeframe: {entry_resolution}",
        f"- Typical hold: 10–30 minutes (time-stop fallback)",
        "- Position: 100 lots",
        "- TP1: +5 points, exit 50 lots",
        "- TP2: +15 points, exit remaining 50 lots",
        f"- Backtest days: {days}",
        "",
        "## Strategy Rules",
        "```json",
        rules_json.strip(),
        "```",
        "",
        "## Backtest Results",
        "",
        "| Technique | Trades | Win Rate | Strategy Return | Buy & Hold | Max Drawdown | Verdict |",
        "|-----------|--------|----------|-----------------|------------|--------------|---------|",
    ]

    for result in results:
        lines.append(
            f"| {result.rule_name} | {result.total_trades} | {result.win_rate}% | "
            f"{result.total_return_pct}% | {result.buy_hold_return_pct}% | "
            f"{result.max_drawdown_pct}% | {result.verdict} |"
        )

    lines.extend(["", "## Signal Stats", ""])
    for result in results:
        lines.append(
            f"- **{result.rule_name}:** {result.sweeps_detected} sweeps detected, "
            f"{result.confirmed_entries} confirmed entries, {result.total_trades} completed trades"
        )

    if any(result.rule_compliance for result in results):
        lines.extend(["", "## Rule Compliance Check", ""])
        for result in results:
            if not result.rule_compliance:
                continue
            lines.append(f"### {result.rule_name}")
            for key, passed in result.rule_compliance.items():
                status = "Yes" if passed else "No"
                label = key.replace("_", " ").title()
                lines.append(f"- {label}: **{status}**")
            lines.append("")

    lines.extend(["", "## Trade Details", ""])
    for result in results:
        lines.extend([f"### {result.rule_name}", ""])
        if not result.trades:
            lines.append("_No trades generated._")
            lines.append("")
            continue

        lines.extend(
            [
                "| Side | Entry | Exit | Entry Price | Exit Price | Lots | Points | SL | TP1 | TP2 | Liquidity | Return | Reason |",
                "|------|-------|------|-------------|------------|------|--------|----|-----|-----|-----------|--------|--------|",
            ]
        )
        for trade in result.trades:
            lines.append(
                f"| {trade.trade_type} | {trade.entry_date} | {trade.exit_date} | "
                f"{trade.entry_price} | {trade.exit_price} | {trade.lots} | {trade.points} | "
                f"{trade.stop_loss} | {trade.take_profit_1} | {trade.take_profit_2} | "
                f"{trade.liquidity_price} | {trade.return_pct}% | {trade.exit_reason} |"
            )
        lines.append("")

    lines.extend(
        [
            "---",
            "_For research only. Past performance does not guarantee future results._",
        ]
    )
    return "\n".join(lines)


def save_report(content: str, path: Path) -> None:
    path.write_text(content, encoding="utf-8")


def save_results_json(results: list[BacktestResult], path: Path) -> None:
    payload = [result_to_dict(result) for result in results]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
