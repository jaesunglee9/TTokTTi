# incident_review/report_v2.py
"""Incident section of the post-work report.

legacy_section(): what the current pipeline can do - the text LLM only sees the
realtime detector's one-line description and free-cites the law.
v2_section(): the LLM writes prose from reviewer-confirmed facts; violations and
citations are decided by the server from the review and the rule catalog.
"""
import json
from typing import List

from .backends import Backend, extract_json
from .catalog import RuleCatalog
from .verifier import Review

LEGACY_PROMPT = """너는 건설현장 안전 보고서 작성자다. 아래 실시간 탐지 기록만 보고 사고 섹션을 작성하라.
현장 규칙: {rule_context}
탐지 기록: {first_stage}

다음 JSON만 출력하라:
{{"violations": [{{"type": "위반 유형(예: 안전모 미착용)", "legal_basis": "관련 법령명과 조문"}}],
  "narrative": "경위 2~3문장", "actions": ["조치사항"]}}"""

V2_PROMPT = """너는 건설현장 안전 보고서 작성자다. 아래 '확정 사실'만 사용해 사고 섹션의 문장을 작성하라.
- 확정 사실에 없는 위반, 수치, 시각을 만들지 마라.
- 법령 조문은 쓰지 마라(서버가 붙인다).
- '확인 필요' 항목은 단정하지 말고 확인이 필요하다고 써라.

확정 사실: {facts}

다음 JSON만 출력하라:
{{"narrative": "경위 2~3문장", "actions": ["조치사항"]}}"""


def legacy_section(backend: Backend, first_stage: str, rule_context: str) -> dict:
    raw = backend.complete(LEGACY_PROMPT.format(rule_context=rule_context, first_stage=first_stage))
    return extract_json(raw)


def v2_section(backend: Backend, catalog: RuleCatalog, review: Review) -> dict:
    confirmed = review.violated()
    needs_check = [rid for rid, c in review.checks.items() if c["result"] == "UNCERTAIN"]
    facts = {
        "violations": [
            {"rule": catalog.get(rid).violation, "observation": review.checks[rid]["observation"],
             "evidence_frames": review.checks[rid]["evidence_frames"]}
            for rid in confirmed
        ],
        "needs_check": [{"rule": catalog.get(rid).title, "note": review.checks[rid]["observation"]} for rid in needs_check],
        "timeline": review.timeline,
    }
    prose = extract_json(backend.complete(V2_PROMPT.format(facts=json.dumps(facts, ensure_ascii=False))))
    # Server-owned fields: which rules were violated and what they cite.
    return {
        "violations": [
            {"rule_id": rid, "type": catalog.get(rid).violation, "legal_basis": catalog.get(rid).citation_text(),
             "citation_type": catalog.get(rid).citation["type"], "evidence_frames": review.checks[rid]["evidence_frames"]}
            for rid in confirmed
        ],
        "needs_check": needs_check,
        "narrative": prose.get("narrative", ""),
        "actions": prose.get("actions", []),
        "catalog_version": catalog.version,
    }


def claimed_rules(section: dict, catalog: RuleCatalog) -> List[str]:
    """Which rules a report section claims were violated (keyword match for legacy prose)."""
    out = []
    for v in section.get("violations", []):
        rid = v.get("rule_id")
        out += [rid] if rid else catalog.match_text(v.get("type", ""))
    return sorted(set(out))
