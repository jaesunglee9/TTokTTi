# incident_review/eval/site_filter.py
"""Classify every alarmed image as a work site or not, uniformly and without labels.

In production frames only arrive during an active work session, so non-work
scenes (selfies at home, meetings) are out of scope. The public dataset mixes them
in; they are excluded from scoring instead of being labelled case by case.
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.backends import extract_json, make_backend  # noqa: E402

PROMPT = """Classify the scene in this image. Do not judge safety gear.
- WORK_SITE: a construction, industrial, utility or other physical work site, or people doing physical work
- NOT_WORK_SITE: clearly not a work context (home, office meeting, selfie at home, street/lobby with no work)
- UNCLEAR: cannot tell
Answer ONLY JSON: {"scene": "WORK_SITE|NOT_WORK_SITE|UNCLEAR", "reason": "<short Korean>"}"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--backend", default="claude:haiku")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    out = args.data / "site_filter.jsonl"

    backend = make_backend(args.backend)
    labels = {r["id"]: r for r in json.loads((args.data / "labels.json").read_text())}
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    alarms = [b["id"] for b in map(json.loads, (args.data / "baseline.jsonl").read_text().splitlines())
              if b["is_danger"] and b["id"] not in done]
    lock = threading.Lock()

    def run(image_id):
        try:
            raw = extract_json(backend.complete(PROMPT, [args.data / labels[image_id]["path"]]))
            scene = raw["scene"] if raw.get("scene") in {"WORK_SITE", "NOT_WORK_SITE", "UNCLEAR"} else "UNCLEAR"
        except Exception as e:
            print(f"ERROR {image_id}: {e}", flush=True)
            return
        with lock, out.open("a") as f:
            f.write(json.dumps({"id": image_id, "scene": scene, "reason": raw.get("reason", ""),
                                "classifier": backend.name}, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, alarms))


if __name__ == "__main__":
    main()
