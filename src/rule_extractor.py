from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class TradingRule:
    name: str
    strategy_type: str
    setup_rules: list[str] = field(default_factory=list)
    entry_rules: list[str] = field(default_factory=list)
    exit_rules: list[str] = field(default_factory=list)
    risk_rules: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    source_quotes: list[str] = field(default_factory=list)


def _extract_quote(text: str, keyword: str, window: int = 160) -> str:
    index = text.find(keyword)
    if index == -1:
        return ""
    start = max(0, index - 50)
    end = min(len(text), index + window)
    return text[start:end].strip()


def _is_liquidity_transcript(text: str) -> bool:
    markers = (
        "लिक्विडिटी",
        "लिक्विडिट",
        "liquidity",
        "एल क्यू डी टी वाई",
        "LQDTY",
    )
    return any(marker in text for marker in markers)


def _extract_liquidity_strategy_rules(text: str) -> list[TradingRule]:
    """Extract the full LQDTY liquidity strategy exactly as described in the transcript."""
    return [
        TradingRule(
            name="LQDTY Liquidity Strategy",
            strategy_type="liquidity",
            setup_rules=[
                "Core principle: LQDTY (Liquidity) — trade where retail stop losses cluster.",
                "Use 1 Day timeframe on the chart.",
                "Take the previous completed day candle (skip the running/current day candle).",
                "Draw two horizontal lines: one at the previous day high and one at the previous day low.",
                "These two lines are the liquidity levels for the next session.",
                "After drawing the lines, switch to the 1 minute timeframe for execution.",
                "Video demonstrates on Gold; the same logic can be adapted to ETH, BTC, or indices after backtesting.",
                "Do not take a trade if price stays in the middle and never reaches a liquidity line.",
                "Set alerts on your broker or TradingView when price approaches a liquidity line.",
            ],
            entry_rules=[
                "Every entry is exactly 100 lots — fixed size, no scaling.",
                "SHORT setup: price must first reach the upper liquidity line (previous day high zone).",
                "SHORT entry: on 1 minute, wait for a fresh red candle after price reaches the upper line.",
                "SHORT trigger: enter on the NEXT candle when it breaks AND closes below the red candle low.",
                "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
                "LONG entry: on 1 minute, wait for a fresh green candle after price reaches the lower line.",
                "LONG trigger: enter on the NEXT candle when it breaks AND closes above the green candle high.",
                "Signal candle must have a strong body (not a doji) and meaningful range.",
                "Skip entries where stop loss is too tight or too wide.",
                "If price is between the two lines, there is no trade.",
            ],
            exit_rules=[
                "Target 1: book partial profit when ETH moves 10 points in your favor.",
                "At target 1, exit 50 lots (50%) only — do NOT close the full 100 lots.",
                "Keep 50 lots as runner — no trailing stop.",
                "Runner stop loss: swing low (long) or swing high (short) from daily lookback.",
                "Target 2 (runner): +20 points from first entry price.",
            ],
            risk_rules=[
                "Stop loss for LONG: below the previous 1m candle wick low (candle before entry).",
                "Stop loss for SHORT: above the previous 1m candle wick high (candle before entry).",
                "After partial profit at 10 points, runner uses swing high/low stop only (no trail).",
                "Always enter with fixed 100 lots on every trade.",
                "Allow a maximum of 2 full stop losses per session (complete SL, not partial exit).",
                "If a trade moves in your favor and you partial-exit or move SL to breakeven, that does not count as a full SL.",
                "If two full stop losses are hit, stop trading for that session.",
                "Only 1 entry attempt per liquidity line per day (upper line = shorts, lower line = longs).",
                "After a full stop loss at the upper line, no more shorts from that line for the rest of the day.",
                "After a full stop loss at the lower line, no more longs from that line for the rest of the day.",
                "If one trade gives partial profit and another gives a full SL, a third attempt is allowed.",
                "Never take more than 3 trades in one sequence.",
                "Avoid entries where stop loss is too wide.",
                "Backtest on ETH futures (e.g. ETHUSD on Delta Exchange).",
            ],
            parameters={
                "setup_timeframe": "1d",
                "entry_timeframe": "1m",
                "lines_from": "previous_day_high_and_low",
                "instrument": "ETHUSD",
                "max_full_stop_losses_per_session": 2,
                "max_trades_per_sequence": 3,
                "max_entries_per_liquidity_line_per_day": 1,
                "entry_on_next_candle": True,
                "require_close_beyond_signal": True,
                "min_stop_loss_points": 3.0,
                "max_stop_loss_points": 7.0,
                "min_reward_to_risk": 1.5,
                "min_signal_body_ratio": 0.55,
                "min_signal_range_points": 2.5,
                "position_lots": 100,
                "partial_exit_lots": 50,
                "runner_lots": 50,
                "partial_target_points": 10,
                "runner_target_points": 20,
                "use_trailing_stop_after_partial": False,
                "trailing_stop_points": 3.0,
                "starting_wallet_usd": 10000,
                "stop_loss_mode": "previous_candle_wick",
                "max_stop_loss_pct": 5.0,
                "swing_lookback_days": 20,
            },
            source_quotes=[
                _extract_quote(text, "वन डे का टाइम फ्रेम")
                or _extract_quote(text, "1 मिनट पे")
                or _extract_quote(text, "लिक्विडिटी"),
            ],
        )
    ]


def _find_number_after(text: str, pattern: str, default: float | int) -> float | int:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return default
    return float(match.group(1)) if "." in match.group(1) else int(match.group(1))


def extract_rules_from_transcript(transcript: str) -> list[TradingRule]:
    """Extract trading rules directly from transcript content."""
    text = " ".join(transcript.split())
    lowered = text.lower()

    if _is_liquidity_transcript(text):
        return _extract_liquidity_strategy_rules(text)

    rules: list[TradingRule] = []

    if any(term in lowered for term in ("golden cross", "moving average cross", "ma cross")):
        fast = int(_find_number_after(lowered, r"(\d+)\s*(?:day|d)?\s*(?:ma|sma|ema)", 50))
        slow = int(
            _find_number_after(
                lowered,
                r"(\d+)\s*(?:day|d)?\s*(?:ma|sma|ema).{0,30}?(\d+)\s*(?:day|d)?\s*(?:ma|sma|ema)",
                200,
            )
        )
        if slow == 200:
            pairs = re.findall(r"(\d+)\s*(?:and|&|,)\s*(\d+)", lowered)
            if pairs:
                fast, slow = int(pairs[0][0]), int(pairs[0][1])

        rules.append(
            TradingRule(
                name="Moving Average Crossover",
                strategy_type="ma_crossover",
                entry_rules=[f"Buy when {fast}-MA crosses above {slow}-MA"],
                exit_rules=[f"Sell when {fast}-MA crosses below {slow}-MA"],
                parameters={"fast_period": fast, "slow_period": slow},
                source_quotes=[_extract_quote(text, "cross") or _extract_quote(text, "moving average")],
            )
        )

    if "macd" in lowered:
        rules.append(
            TradingRule(
                name="MACD Crossover",
                strategy_type="macd",
                entry_rules=["Buy when MACD line crosses above signal line"],
                exit_rules=["Sell when MACD line crosses below signal line"],
                parameters={"fast": 12, "slow": 26, "signal": 9},
                source_quotes=[_extract_quote(text, "macd")],
            )
        )

    return rules


def rules_to_json(rules: list[TradingRule]) -> str:
    return json.dumps([asdict(rule) for rule in rules], indent=2, ensure_ascii=False)


def rules_from_json(raw: str) -> list[TradingRule]:
    data = json.loads(raw)
    return [TradingRule(**item) for item in data]
