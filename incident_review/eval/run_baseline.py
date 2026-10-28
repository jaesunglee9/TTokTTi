# incident_review/eval/run_baseline.py
"""Stage 1 (realtime detector) reproduction.

Same prompt and rule context as vision_bodycam/core/inference.py detect_danger and
core/rag.py DynamicRetriever default. Production runs Qwen3-VL-8B AWQ on vLLM;
an 8GB Turing GPU cannot host that, so this uses a smaller Qwen3-VL by default.
The model id is recorded with every row.
"""
import argparse
import json
import sys
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from incident_review.eval.stage1_prompt import PROMPT  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-VL-2B-Instruct")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or args.data / "baseline.jsonl"

    done = {json.loads(l)["id"] for l in out.read_text().splitlines()} if out.exists() else set()
    rows = [r for r in json.loads((args.data / "labels.json").read_text()) if r["id"] not in done]

    processor = AutoProcessor.from_pretrained(args.model)
    model = AutoModelForImageTextToText.from_pretrained(args.model, torch_dtype=torch.float16, device_map="cuda")

    with out.open("a") as f:
        for i, r in enumerate(rows, 1):
            image = Image.open(args.data / r["path"]).convert("RGB")
            messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
            inputs = processor.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True, return_dict=True, return_tensors="pt"
            ).to(model.device)
            with torch.no_grad():
                ids = model.generate(**inputs, max_new_tokens=100, do_sample=False)
            text = processor.batch_decode(ids[:, inputs["input_ids"].shape[1]:], skip_special_tokens=True)[0].strip()
            f.write(json.dumps({"id": r["id"], "model": args.model, "text": text,
                                "is_danger": text.upper().startswith("DANGER")}, ensure_ascii=False) + "\n")
            f.flush()
            print(f"[{i}/{len(rows)}] {text[:80]}")


if __name__ == "__main__":
    main()
