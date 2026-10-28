# incident_review/eval/run_review.py
"""Stage 2 + reports for every stage-1 alarm (is_danger) - the incidents a report would be written for.

Each still image stands in for one highlight window (frame id f_0001).
Writes one row per alarm: the review, a legacy report section and a v2 section.
"""
import argparse
import json
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.backends import make_backend  # noqa: E402
from incident_review.catalog import RuleCatalog  # noqa: E402
from incident_review.eval.stage1_prompt import RULE_CONTEXT  # noqa: E402
from incident_review.report_v2 import legacy_section, v2_section  # noqa: E402
from incident_review.verifier import review_window  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--backend", default="claude")
    ap.add_argument("--limit", type=int, default=None, help="sample this many alarms (seed 7) for a dry run")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or args.data / "review.jsonl"

    catalog = RuleCatalog()
    backend = make_backend(args.backend)
    labels = {r["id"]: r for r in json.loads((args.data / "labels.json").read_text())}
    alarms = [b for b in map(json.loads, (args.data / "baseline.jsonl").read_text().splitlines()) if b["is_danger"]]
    if args.limit:
        alarms = random.Random(7).sample(alarms, min(args.limit, len(alarms)))
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()

    lock = threading.Lock()

    def run(b):
        frames = {"f_0001": args.data / labels[b["id"]]["path"]}
        row = {"id": b["id"], "backend": backend.name, "catalog_version": catalog.version}
        try:
            review = review_window(backend, catalog, frames, catalog.ids(), b["text"])
            row["review"] = {"checks": review.checks, "timeline": review.timeline,
                             "uncertainties": review.uncertainties, "rejected": review.rejected}
            row["legacy"] = legacy_section(backend, b["text"], RULE_CONTEXT)
            row["v2"] = v2_section(backend, catalog, review)
        except Exception as e:  # recorded, never silently counted as a pass
            row["error"] = f"{type(e).__name__}: {e}"[:500]
        with lock, out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{b['id'][:40]} -> {row.get('error') or [c['result'] for c in row['review']['checks'].values()]}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, [a for a in alarms if a["id"] not in done]))


if __name__ == "__main__":
    main()
