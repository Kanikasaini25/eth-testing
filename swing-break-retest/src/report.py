from __future__ import annotations

import json
from pathlib import Path

from src.backtest import BacktestResult, result_to_dict


def generate_report(
    rules_json: str,
    results: list[BacktestResult],
    symbol: str,
    days: int,
) -> str:
    lines = [
        "# 30M Swing Break + 5M Retest — Backtest Report",
        "",
        "## Strategy",
        "Mark the 30-minute swing high and swing low. When either swing is broken, "
        "wait for price to retest the broken level on the 5-minute chart. "
        "Enter in the same direction as the breakout.",
        "",
        "| 30M Event | 5M Action | Trade |",
        "|-----------|-----------|-------|",
        "| Swing High breaks | Retest of Swing High | LONG |",
        "| Swing Low breaks | Retest of Swing Low | SHORT |",
        "| No break | Wait | NO TRADE |",
        "",
        "## Market Data",
        f"- Symbol: {symbol}",
        "- Setup timeframe: 30m",
        "- Entry timeframe: 5m",
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
            f"- **{result.rule_name}:** {result.breaks_detected} breaks detected, "
            f"{result.retest_entries} retest entries, {result.total_trades} completed trades"
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
                "| Side | Entry | Exit | Entry Price | Exit Price | SL | TP | Broken Level | Return | Reason |",
                "|------|-------|------|-------------|------------|----|----|--------------|--------|--------|",
            ]
        )
        for trade in result.trades:
            lines.append(
                f"| {trade.trade_type} | {trade.entry_date} | {trade.exit_date} | "
                f"{trade.entry_price} | {trade.exit_price} | {trade.stop_loss} | "
                f"{trade.take_profit} | {trade.broken_level} | {trade.return_pct}% | "
                f"{trade.exit_reason} |"
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
