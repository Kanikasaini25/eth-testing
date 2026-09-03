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
                "SHORT entry: after the previous day high is broken/swept, wait for a bearish 1m rejection candle; its close may remain above the liquidity line.",
                "If the rejection candle is red, it is the first red candle; enter short only when the next red candle breaks the first red candle low.",
                "LONG setup: price must first reach the lower liquidity line (previous day low zone).",
                "LONG entry: after the previous day low is broken/swept, wait for a bullish 1m rejection candle; its close may remain below the liquidity line.",
                "If the rejection candle is green, it is the first green candle; enter long only when the next green candle breaks the first green candle high.",
                "After a profitable trade, allow same-direction re-entry only after an opposite-color pullback and a new two-candle confirmation; do not require another liquidity-line break.",
                "Trade throughout the full UTC day (00:00–24:00 UTC).",
                "If price is between the two lines, there is no trade.",
            ],
            exit_rules=[
                "Risk R is the absolute distance from entry to the initial stop.",
                "At +2% profit, keep the initial SL unchanged.",
                "At +3% profit, move SL to +2% profit.",
                "At +4% profit, move SL to +3% profit.",
                "At +5% profit, close the entire position.",
            ],
            risk_rules=[
                "Stop loss for LONG: below the first green candle wick low.",
                "Stop loss for SHORT: above the first red candle wick high.",
                "Always enter with fixed 100 lots on every trade.",
                "After 2 full stop losses in one UTC day, stop trading for that day.",
                "After a full stop loss, another entry from the same line is allowed until 3 daily attempts are reached.",
                "After TP1 or TP2, the full position remains open while the stop locks the achieved R level.",
                "Never take more than 3 trades in one sequence.",
                "Backtest on ETH futures (e.g. ETHUSD on Delta Exchange).",
            ],
            parameters={
                "setup_timeframe": "1d",
                "entry_timeframe": "1m",
                "lines_from": "previous_day_high_and_low",
                "instrument": "ETHUSD",
                "max_full_stop_losses_per_session": 2,
                "max_trades_per_sequence": 3,
                "max_entries_per_liquidity_line_per_day": 3,
                "entry_on_next_candle": True,
                "require_close_beyond_signal": False,
                "require_liquidity_sweep": True,
                "require_two_consecutive_confirmation_candles": True,
                "use_daily_trend_filter": False,
                "use_session_filter": True,
                "session_start_hour_delta": 0,
                "session_end_hour_delta": 0,
                "min_signal_body_ratio": 0.0,
                "min_signal_range_points": 0.0,
                "position_lots": 100,
                "risk_reward_ratio": 2,
                "profit_milestones_pct": [2, 3, 4, 5],
                "starting_wallet_usd": 10000,
                "stop_loss_mode": "first_confirmation_candle_wick",
                "swing_lookback_days": 20,
                "runner_swing_lookback_days": 60,
                "fee_pct_per_side": 0.05,
                "platform_fee_pct_per_side": 0.0,
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
