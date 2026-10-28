# incident_review/verifier.py
"""Stage 2: a larger multimodal model re-checks a highlight window against the rule catalog.

The model answers each rule's visual check with VIOLATED / NOT_VIOLATED / UNCERTAIN
and must cite frame ids. The server rejects unknown rules, unknown frames and
VIOLATED answers without evidence, so a confident but ungrounded answer cannot
become a fact in the report.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .backends import Backend, extract_json
from .catalog import RuleCatalog

RESULTS = {"VIOLATED", "NOT_VIOLATED", "UNCERTAIN"}

PROMPT = """You are a construction-site safety reviewer. The frames below come from one highlight
window of a worker bodycam/site camera (frame ids are given in order).

Context from the realtime detector (may be wrong): {first_stage}

For EACH rule below, decide from the frames only:
- VIOLATED: you can clearly see a worker breaking the rule
- NOT_VIOLATED: workers are visible and the rule is clearly followed, or no worker the rule applies to is visible
- UNCERTAIN: occluded, too small, blurry, or otherwise not decidable
Do not guess. Prefer UNCERTAIN over a wrong VIOLATED.

Rules:
{rules}

Frames: {frames}

Answer with ONLY this JSON (observation in Korean, one sentence):
{{"rule_checks": [{{"rule_id": "...", "result": "VIOLATED|NOT_VIOLATED|UNCERTAIN", "evidence_frames": ["..."], "observation": "..."}}],
  "timeline": [{{"frame": "...", "what": "..."}}],
  "uncertainties": ["..."]}}"""


@dataclass
class Review:
    checks: Dict[str, dict]
    timeline: List[dict]
    uncertainties: List[str]
    rejected: List[str] = field(default_factory=list)

    def violated(self) -> List[str]:
        return [rid for rid, c in self.checks.items() if c["result"] == "VIOLATED"]


def review_window(
    backend: Backend,
    catalog: RuleCatalog,
    frames: Dict[str, Path],
    rule_ids: List[str],
    first_stage: str,
) -> Review:
    rules = "\n".join(f"- {rid}: {catalog.get(rid).check}" for rid in rule_ids)
    prompt = PROMPT.format(first_stage=first_stage or "(none)", rules=rules, frames=", ".join(frames))
    raw = extract_json(backend.complete(prompt, list(frames.values())))
    return validate(raw, rule_ids, set(frames))


def validate(raw: dict, rule_ids: List[str], frame_ids: set) -> Review:
    checks: Dict[str, dict] = {}
    rejected: List[str] = []
    for c in raw.get("rule_checks", []):
        rid, result = c.get("rule_id"), c.get("result")
        if rid not in rule_ids or result not in RESULTS:
            rejected.append(f"UNKNOWN_RULE_OR_RESULT:{rid}:{result}")
            continue
        evidence = [f for f in c.get("evidence_frames", []) if f in frame_ids]
        if result == "VIOLATED" and not evidence:
            # Grounding policy: a violation must point at a frame we actually sent.
            rejected.append(f"VIOLATION_WITHOUT_EVIDENCE:{rid}")
            result = "UNCERTAIN"
        checks[rid] = {"result": result, "evidence_frames": evidence, "observation": c.get("observation", "")}
    for rid in rule_ids:
        checks.setdefault(rid, {"result": "UNCERTAIN", "evidence_frames": [], "observation": "응답 없음"})
    timeline = [t for t in raw.get("timeline", []) if t.get("frame") in frame_ids]
    return Review(checks, timeline, list(raw.get("uncertainties", [])), rejected)
