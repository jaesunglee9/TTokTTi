"""Real GPU inference for the browser demo. Never writes safety incidents to Django."""
import asyncio
import base64
import io
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vision_bodycam"))
from latency import FrameTiming, elapsed_ms
import redis.asyncio as redis
from PIL import Image
import torch
from transformers import AutoProcessor, Qwen3VLForConditionalGeneration, StoppingCriteria, StoppingCriteriaList

MODEL_ID = "Qwen/Qwen3-VL-2B-Instruct"
MODEL_REVISION = "89644892e4d85e24eaac8bacfd4f463576704203"
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6391/0")
MAX_TOKENS = 64
PROMPT = ("Reply in Korean in at most two short sentences. Describe the visible scene and any directly "
          "observable physical safety concern. If uncertain, say you cannot judge. Do not assume hidden "
          "equipment or events. This is a demonstration, not a workplace safety assessment.")

class FirstToken(StoppingCriteria):
    def __init__(self, started):
        self.started = started
        self.first_ms = None
    def __call__(self, input_ids, scores, **kwargs):
        if self.first_ms is None:
            torch.cuda.synchronize()
            self.first_ms = elapsed_ms(self.started)
        return False

class Engine:
    def __init__(self):
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA GPU required for this benchmark; no silent CPU fallback")
        start = time.perf_counter()
        self.processor = AutoProcessor.from_pretrained(MODEL_ID, revision=MODEL_REVISION,
                                                       min_pixels=64*32*32, max_pixels=196*32*32)
        self.model = Qwen3VLForConditionalGeneration.from_pretrained(
            MODEL_ID, revision=MODEL_REVISION, dtype=torch.float16, attn_implementation="sdpa"
        ).to("cuda").eval()
        torch.cuda.synchronize()
        self.load_ms = elapsed_ms(start)
        self.calls = 0
        self.metadata = {"model": MODEL_ID, "revision": MODEL_REVISION, "dtype": "float16",
                         "device": torch.cuda.get_device_name(0), "max_new_tokens": MAX_TOKENS,
                         "model_load_ms": self.load_ms, "transformers": __import__("transformers").__version__,
                         "torch": torch.__version__, "mode": "browser_demo_single_frame"}
    @torch.inference_mode()
    def infer(self, encoded):
        start = time.perf_counter()
        encoded = encoded.split(",", 1)[-1]
        if len(encoded) > 8_000_000:
            raise ValueError("Image exceeds demo size limit")
        image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True)))
        image.load()
        image = image.convert("RGB")
        image.thumbnail((448, 448))
        decode_ms = elapsed_ms(start)
        prep = time.perf_counter()
        messages = [{"role": "user", "content": [
            {"type": "image", "image": image}, {"type": "text", "text": PROMPT}]}]
        inputs = self.processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                                   return_dict=True, return_tensors="pt").to("cuda")
        torch.cuda.synchronize()
        prepare_ms = elapsed_ms(prep)
        generate_start = time.perf_counter()
        first = FirstToken(generate_start)
        generated = self.model.generate(**inputs, max_new_tokens=MAX_TOKENS, do_sample=False,
                                        stopping_criteria=StoppingCriteriaList([first]))
        torch.cuda.synchronize()
        generate_ms = elapsed_ms(generate_start)
        post_start = time.perf_counter()
        ids = generated[0, inputs.input_ids.shape[1]:]
        text = self.processor.decode(ids, skip_special_tokens=True).strip()
        if not text:
            raise RuntimeError("Model returned an empty response")
        self.calls += 1
        return {
            "analysis": {"text": text, "output_tokens": len(ids), "input_tokens": inputs.input_ids.shape[1],
                         "token_limit_reached": len(ids) >= MAX_TOKENS, "model_call": self.calls},
            "timing": {"image_decode_ms": decode_ms, "model_prepare_ms": prepare_ms,
                       "model_generate_ms": generate_ms, "first_token_ms": first.first_ms,
                       "model_decode_tail_ms": round(generate_ms - first.first_ms, 3),
                       "output_decode_ms": elapsed_ms(post_start)},
        }

async def main():
    logging.basicConfig(level=logging.INFO)
    r = redis.from_url(REDIS_URL, decode_responses=True)
    await r.ping()
    engine = await asyncio.to_thread(Engine)
    print(json.dumps({"event": "model_ready", **engine.metadata}), flush=True)
    async def heartbeat():
        while True:
            await r.set("latency_demo:worker", json.dumps({"ready": True, **engine.metadata}), ex=10)
            await asyncio.sleep(2)
    beat = asyncio.create_task(heartbeat())
    log_path = Path(os.getenv("DEMO_LOG", "/tmp/ttoktti-runtime/demo-worker-samples.jsonl"))
    try:
        while True:
            item = await r.brpop("video_frames", timeout=1)
            if not item:
                continue
            job = json.loads(item[1])
            timing = FrameTiming(job.get("_latency"))
            await timing.dequeue(r)
            try:
                output = await asyncio.to_thread(engine.infer, job["data"]["image"])
                timing.metrics.update(output["timing"])
                response = {**timing.result("ok"), "analysis": output["analysis"],
                            "model": engine.metadata["model"], "mode": "browser_demo"}
            except Exception as error:
                response = {**timing.result("error"), "error": str(error)[:300], "mode": "browser_demo"}
                logging.exception("Demo inference failed")
            # Metrics omit images and generated text in the on-disk raw performance log.
            record = {k: v for k, v in response.items() if k != "analysis"}
            record["analysis_stats"] = {k: v for k, v in response.get("analysis", {}).items() if k != "text"}
            with log_path.open("a") as out:
                out.write(json.dumps(record) + "\n")
            await r.publish(f"alerts:{job['client_id']}", json.dumps(response))
    finally:
        beat.cancel()
        await r.aclose()

if __name__ == "__main__":
    asyncio.run(main())
