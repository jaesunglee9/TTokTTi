# incident_review/eval/run_stage1_cli.py
"""Stage 1 reproduction through a CLI backend instead of a local GPU.

A small, fast model (default claude:haiku) stands in for the realtime Qwen3-VL-8B
and gets the verbatim detect_danger prompt. Output format matches run_baseline.py.
"""
import argparse
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.backends import make_backend  # noqa: E402
from incident_review.eval.stage1_prompt import PROMPT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--backend", default="claude:haiku")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or args.data / "baseline.jsonl"

    backend = make_backend(args.backend)
    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    rows = [r for r in json.loads((args.data / "labels.json").read_text()) if r["id"] not in done]
    lock = threading.Lock()

    def run(r):
        try:
            text = backend.complete(PROMPT, [args.data / r["path"]]).strip()
            row = {"id": r["id"], "model": backend.name, "text": text, "is_danger": text.upper().startswith("DANGER")}
        except Exception as e:
            print(f"ERROR {r['id']}: {e}", flush=True)  # left out of the file so a rerun retries it
            return
        with lock, out.open("a") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{r['id'][:40]} {text[:70]}", flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, rows))


if __name__ == "__main__":
    main()
