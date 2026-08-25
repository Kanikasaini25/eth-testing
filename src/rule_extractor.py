from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
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


def rules_to_json(rules: list[TradingRule]) -> str:
    return json.dumps([asdict(rule) for rule in rules], indent=2, ensure_ascii=False)


def rules_from_json(raw: str) -> list[TradingRule]:
    data = json.loads(raw)
    rules = []
    for item in data:
        item.pop("source_quotes", None)
        rules.append(TradingRule(**item))
    return rules


def load_rules(path: Path) -> list[TradingRule]:
    if not path.exists():
        raise FileNotFoundError(f"Strategy rules not found: {path}")
    rules = rules_from_json(path.read_text(encoding="utf-8"))
    if not rules:
        raise ValueError(f"No trading rules found in {path}")
    return rules
