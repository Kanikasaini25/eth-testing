from __future__ import annotations

import json
from pathlib import Path

from src.backtest import BacktestResult, result_to_dict


def generate_report(
    video_url: str,
    transcript: str,
    rules_json: str,
    results: list[BacktestResult],
    symbol: str,
    resolution: str,
    base_url: str,
) -> str:
    lines = [
        "# Strategy Backtest Report",
        "",
        "## Video",
        f"- URL: {video_url}",
        "",
        "## Market Data",
        f"- API: {base_url}",
        f"- Symbol: {symbol}",
        f"- Timeframe: {resolution}",
        "",
        "## Extracted Techniques",
        "```json",
        rules_json.strip(),
        "```",
        "",
        "## Backtest Results",
        "",
        "_Note: LQDTY liquidity rules use 1D setup + 1M entry in the video. "
        "The backtest below is a daily ETH approximation only._",
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

    lines.extend(["", "## Backtest Mode", ""])
    for result in results:
        lines.append(f"- **{result.rule_name}:** `{result.backtest_mode}`")

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
                "| Entry | Exit | Entry Price | Exit Price | Points | P/L ($) | Reason |",
                "|-------|------|-------------|------------|--------|---------|--------|",
            ]
        )
        for trade in result.trades:
            lines.append(
                f"| {trade.entry_date} | {trade.exit_date} | {trade.entry_price} | "
                f"{trade.exit_price} | {trade.points} | ${trade.pnl_usd:+.2f} | {trade.exit_reason} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Transcript Excerpt",
            "",
            transcript[:1500] + ("..." if len(transcript) > 1500 else ""),
            "",
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
