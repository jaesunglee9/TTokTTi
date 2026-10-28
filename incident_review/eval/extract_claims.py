# incident_review/eval/extract_claims.py
"""Which rules does each stage-1 alarm sentence actually allege?

Keyword matching over-counts ("wears a hard hat but no vest" mentions the hard hat
without alleging a hard-hat violation), which would inflate stage-1 false positives
and flatter the review stage. A small text model reads only the sentence - never the
image or the label - and returns the alleged rule ids.
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.backends import extract_json, make_backend  # noqa: E402

PROMPT = """A safety alarm said: "{text}"

Which of these violations does the sentence ASSERT is happening (not merely mention)?
- PPE-HARDHAT: a worker is not wearing a hard hat / helmet
- PPE-VEST: a worker is not wearing a high-visibility safety vest
"may not be wearing" counts as asserted. "wears a hard hat but no vest" asserts only PPE-VEST.
Answer ONLY JSON: {{"rules": ["..."]}}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--backend", default="claude:haiku")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    out = args.data / "stage1_claims.jsonl"

    backend = make_backend(args.backend)
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    alarms = [b for b in map(json.loads, (args.data / "baseline.jsonl").read_text().splitlines())
              if b["is_danger"] and b["id"] not in done]
    lock = threading.Lock()

    def run(b):
        try:
            rules = extract_json(backend.complete(PROMPT.format(text=b["text"])))["rules"]
        except Exception as e:
            print(f"ERROR {b['id']}: {e}", flush=True)
            return
        rules = sorted(r for r in set(rules) if r in {"PPE-HARDHAT", "PPE-VEST"})
        with lock, out.open("a") as f:
            f.write(json.dumps({"id": b["id"], "rules": rules, "extractor": backend.name}) + "\n")

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, alarms))


if __name__ == "__main__":
    main()
