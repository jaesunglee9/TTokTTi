# incident_review/catalog.py
"""Rule catalog: rule_id -> visual check + legal citation.

The VLM never chooses a law. It only answers the visual check for each rule;
the citation always comes from this human-reviewed catalog.
"""
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

CATALOG_PATH = Path(__file__).with_name("rule_catalog.json")


@dataclass(frozen=True)
class Rule:
    rule_id: str
    title: str
    violation: str
    check: str
    keywords: List[str]
    citation: Dict[str, Any]

    def citation_text(self) -> str:
        c = self.citation
        if c["type"] == "STATUTE":
            return f"{c['law']} {c['article']}"
        return "현장 내부 규정(법정 조문 없음)"


class RuleCatalog:
    def __init__(self, path: Path = CATALOG_PATH):
        data = json.loads(path.read_text(encoding="utf-8"))
        self.version: str = data["version"]
        self.rules: Dict[str, Rule] = {
            r["rule_id"]: Rule(r["rule_id"], r["title"], r["violation"], r["check"], r["keywords"], r["citation"])
            for r in data["rules"]
        }

    def get(self, rule_id: str) -> Optional[Rule]:
        return self.rules.get(rule_id)

    def ids(self) -> List[str]:
        return list(self.rules)

    def match_text(self, text: str) -> List[str]:
        """Map free text (e.g. a 1st-stage 'DANGER: ...' sentence) to rule ids by keyword."""
        lowered = text.lower()
        return [rid for rid, r in self.rules.items() if any(k.lower() in lowered for k in r.keywords)]
