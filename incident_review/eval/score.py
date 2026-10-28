# incident_review/eval/score.py
"""Score stage-1 alone vs stage-1 + review, and legacy vs v2 report sections.

Unit: (image, rule) claims on images where that rule has a label. Claims on
unlabeled rules are counted but never scored. Rows with errors are excluded
from both sides so before/after compare the same incidents.
"""
import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.catalog import RuleCatalog  # noqa: E402
from incident_review.report_v2 import claimed_rules  # noqa: E402

ARTICLE = re.compile(r"제\s*\d+\s*조")


def hardhat_citation_ok(text: str) -> bool:
    return bool(re.search(r"제\s*32\s*조", text)) and "안전보건기준" in text.replace(" ", "")


def rate(num, den):
    return None if den == 0 else num / den


def bootstrap(ids, fn, n=2000, seed=7):
    rng = random.Random(seed)
    vals = []
    for _ in range(n):
        sample = [rng.choice(ids) for _ in ids]
        v = fn(sample)
        if v is not None:
            vals.append(v)
    vals.sort()
    return (vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]) if vals else (None, None)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--review", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--adjudication", type=Path, default=None, help="human verdicts on disputed cases")
    args = ap.parse_args()

    catalog = RuleCatalog()
    labels = {r["id"]: r["labels"] for r in json.loads((args.data / "labels.json").read_text())}
    adjudicated = 0
    if args.adjudication:
        # Human verdicts replace dataset labels on disputed cases; UNCERTAIN and
        # still-pending cases become unscored rather than guessed.
        adj = json.loads(args.adjudication.read_text())
        for it in adj["items"]:
            labels[it["id"]][it["rule"]] = None if it["human"] == "UNCERTAIN" else it["human"]
            adjudicated += 1
        disputed = {it["n"]: it for it in json.loads((args.data / "dispute" / "items.json").read_text())}
        for n in adj.get("pending", []):
            labels[disputed[n]["id"]][disputed[n]["rule"]] = None
    base = {b["id"]: b for b in map(json.loads, (args.data / "baseline.jsonl").read_text().splitlines())}
    rows = [json.loads(l) for l in (args.review or args.data / "review.jsonl").read_text().splitlines()]
    claims_file = args.data / "stage1_claims.jsonl"
    stage1_rules = (
        {c["id"]: c["rules"] for c in map(json.loads, claims_file.read_text().splitlines())}
        if claims_file.exists() else {}
    )
    # Without extracted claims, fall back to keywords (over-counts; reported in the output).
    ok = [r for r in rows if "error" not in r and (not stage1_rules or r["id"] in stage1_rules)]
    extra_articles = {"legacy": collections.Counter(), "v2": collections.Counter()}

    # Per-image tallies so the bootstrap can resample incidents.
    per = {}
    for r in ok:
        lab = labels[r["id"]]
        s1 = stage1_rules[r["id"]] if stage1_rules else catalog.match_text(base[r["id"]]["text"])
        checks = r["review"]["checks"]
        t = dict(s1_tp=0, s1_fp=0, rv_tp=0, rv_fp=0, unspecified=int(not s1),
                 true_viol=sum(v == "VIOLATED" for v in lab.values()),
                 hh_true=int(lab["PPE-HARDHAT"] == "VIOLATED"))
        for rid in s1:
            if lab.get(rid) is None:
                continue
            truth = lab[rid] == "VIOLATED"
            t["s1_tp" if truth else "s1_fp"] += 1
            if checks[rid]["result"] == "VIOLATED":
                t["rv_tp" if truth else "rv_fp"] += 1
        for name in ("legacy", "v2"):
            claims = [c for c in claimed_rules(r[name], catalog) if lab.get(c) is not None]
            t[f"{name}_claims"] = len(claims)
            t[f"{name}_false"] = sum(lab[c] == "NOT_VIOLATED" for c in claims)
            t[f"{name}_hh_ok"] = 0
            t[f"{name}_vest_statute"] = 0
            cited = set()
            for v in r[name].get("violations", []):
                cited |= {re.sub(r"\s", "", a) for a in ARTICLE.findall(v.get("legal_basis", "") or "")}
            # Articles beyond the catalog's reviewed one (제32조) are unreviewed legal claims.
            t[f"{name}_extra_articles"] = len(cited - {"제32조"})
            extra_articles[name].update(cited - {"제32조"})
            for v in r[name].get("violations", []):
                rids = [v["rule_id"]] if v.get("rule_id") else catalog.match_text(v.get("type", ""))
                basis = v.get("legal_basis", "") or ""
                if "PPE-HARDHAT" in rids and lab["PPE-HARDHAT"] == "VIOLATED" and hardhat_citation_ok(basis):
                    t[f"{name}_hh_ok"] = 1
                if "PPE-VEST" in rids and ARTICLE.search(basis):
                    t[f"{name}_vest_statute"] += 1
        per[r["id"]] = t

    ids = list(per)

    def s(key, sample=None):
        return sum(per[i][key] for i in (sample or ids))

    def fp_reduction(sample):
        before = s("s1_fp", sample)
        return None if before == 0 else 1 - s("rv_fp", sample) / before

    def tp_retention(sample):
        return rate(s("rv_tp", sample), s("s1_tp", sample))

    def fact_err(name):
        return lambda sample: rate(s(f"{name}_false", sample), s(f"{name}_claims", sample))

    def cite_acc(name):
        return lambda sample: rate(s(f"{name}_hh_ok", sample), s("hh_true", sample))

    result = {
        "incidents_reviewed": len(ok),
        "review_errors": len(rows) - len(ok),
        "stage1_alarms_without_rule_keyword": s("unspecified"),
        "stage1": {"tp": s("s1_tp"), "fp": s("s1_fp"), "precision": rate(s("s1_tp"), s("s1_tp") + s("s1_fp"))},
        "stage1_plus_review": {"tp": s("rv_tp"), "fp": s("rv_fp"), "precision": rate(s("rv_tp"), s("rv_tp") + s("rv_fp"))},
        "false_positive_reduction": {"value": fp_reduction(ids), "ci95": bootstrap(ids, fp_reduction)},
        "true_positive_retention": {"value": tp_retention(ids), "ci95": bootstrap(ids, tp_retention)},
        "report_fact_error_rate": {
            n: {"value": fact_err(n)(ids), "ci95": bootstrap(ids, fact_err(n)), "claims": s(f"{n}_claims")}
            for n in ("legacy", "v2")
        },
        "hardhat_citation_accuracy": {
            n: {"value": cite_acc(n)(ids), "ci95": bootstrap(ids, cite_acc(n)), "true_hardhat_incidents": s("hh_true")}
            for n in ("legacy", "v2")
        },
        "vest_cited_as_statute": {n: s(f"{n}_vest_statute") for n in ("legacy", "v2")},
        "unreviewed_articles": {
            n: {"reports_with_any": sum(per[i][f"{n}_extra_articles"] > 0 for i in ids),
                "total": s(f"{n}_extra_articles"), "most_common": extra_articles[n].most_common(10)}
            for n in ("legacy", "v2")
        },
        "stage1_claim_source": "llm_extraction" if stage1_rules else "keyword_fallback",
        "human_adjudicated_cases": adjudicated,
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    (args.out or args.data / "score.json").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
