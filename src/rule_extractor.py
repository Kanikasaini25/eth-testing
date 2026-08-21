from __future__ import annotations

import json
from dataclasses import dataclass, field
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


def rules_from_json(raw: str) -> list[TradingRule]:
    data = json.loads(raw)
    return [TradingRule(**item) for item in data]
