"""Isolated contract tests: fake Redis/model; no GPU, network, or database writes.
Run with a Python environment containing FastAPI, httpx and Pillow.
"""
import asyncio
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "vision_bodycam"))


class FakePubsub:
    def __init__(self):
        self.queue = asyncio.Queue()
    async def subscribe(self, *_): pass
    async def unsubscribe(self, *_): pass
    async def close(self): pass
    async def listen(self):
        while True:
            yield await self.queue.get()


class FakeRedis:
    def __init__(self):
        self.events = []
        self.jobs = []
        self.sub = FakePubsub()
        self.clock = 1000
        self.process = None
    def pubsub(self): return self.sub
    async def time(self):
        self.clock += 10
        return [0, self.clock * 1000]
    async def hset(self, *_, **__): pass
    async def expire(self, *_): pass
    async def ltrim(self, *_): pass
    async def aclose(self): pass
    async def lpush(self, queue, payload):
        self.jobs.append((queue, json.loads(payload)))
        if self.process:
            await self.process(queue, payload)
    async def publish(self, channel, value):
        self.events.append(json.loads(value))
        await self.sub.queue.put({"type": "message", "data": value})


redis = types.ModuleType("redis")
redis_async = types.ModuleType("redis.asyncio")
redis_async.Redis = FakeRedis
redis_async.from_url = lambda *a, **k: FakeRedis()
redis.asyncio = redis_async
inference = types.ModuleType("core.inference")
inference.SafetyAnalyzer = lambda **_: None
rag = types.ModuleType("core.rag")
rag.DynamicRetriever = lambda: None
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
with patch.dict(sys.modules, {"redis": redis, "redis.asyncio": redis_async,
                             "core.inference": inference, "core.rag": rag, "dotenv": dotenv}):
    gateway = importlib.import_module("gateway")
    worker = importlib.import_module("worker")
from latency import FrameTiming
from vision_fullcam.latency import PipelineLatency
from fastapi.testclient import TestClient


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_redis_clock_and_invalid_metadata(self):
        timing = FrameTiming({"version": 1, "frame_id": "frame-1", "enqueued_redis_ms": 900, "gateway_prepare_ms": 3})
        await timing.dequeue(FakeRedis())
        self.assertEqual(timing.metrics["queue_age_ms"], 110)
        self.assertEqual(timing.result("ok")["frame_id"], "frame-1")
        backwards = FrameTiming({"version": 1, "frame_id": "frame-1", "enqueued_redis_ms": 2000})
        await backwards.dequeue(FakeRedis())
        self.assertNotIn("queue_age_ms", backwards.metrics)
        for id in ["", "a" * 97, "bad\nframe", {}, None]:
            self.assertFalse(FrameTiming({"version": 1, "frame_id": id}).enabled)

    async def test_safe_danger_error_and_legacy(self):
        redis = FakeRedis()
        analyzer = types.SimpleNamespace(detect_action=AsyncMock(return_value="work"),
                                         detect_danger=AsyncMock(return_value={"is_danger": False}))
        retriever = types.SimpleNamespace(get_context=lambda *_a, **_k: "rule")
        job = {"client_id": "isolated-test", "data": {"image": "test"},
               "_latency": {"version": 1, "frame_id": "f-1", "enqueued_redis_ms": 1000}}
        with patch.object(worker, "redis_client", redis), patch.object(worker, "analyzer", analyzer), patch.object(worker, "retriever", retriever), patch.object(worker, "report_to_django", AsyncMock()) as report:
            worker.client_memory_cache = worker.FIFOSafeCache(100)
            await worker.process_job("video_frames", json.dumps(job))
            self.assertEqual([e["type"] for e in redis.events], ["FRAME_RESULT"])
            self.assertEqual(redis.events[-1]["status"], "ok")
            self.assertIn("danger_check_ms", redis.events[-1]["timing"])
            report.assert_not_awaited()
            analyzer.detect_danger.return_value = {"is_danger": True, "details": "test"}
            redis.events.clear()
            await worker.process_job("video_frames", json.dumps(job))
            self.assertEqual([e["type"] for e in redis.events], ["DANGER", "FRAME_RESULT"])
            await asyncio.sleep(0)  # Finish the stubbed report task.
            report.assert_awaited_once()
            self.assertEqual(report.await_args.args[:2], ("isolated-test", "test"))
            analyzer.detect_danger.side_effect = RuntimeError("controlled model failure")
            redis.events.clear()
            await worker.process_job("video_frames", json.dumps(job))
            self.assertEqual(redis.events[-1]["status"], "error")
            self.assertEqual(report.await_count, 1)
            analyzer.detect_danger.side_effect = None
            analyzer.detect_danger.return_value = {"is_danger": False}
            redis.events.clear()
            job.pop("_latency")
            await worker.process_job("video_frames", json.dumps(job))
            self.assertEqual(redis.events, [])

    async def test_telemetry_clock_failure_does_not_skip_inference(self):
        redis = FakeRedis()
        redis.time = AsyncMock(side_effect=RuntimeError("clock unavailable"))
        analyzer = types.SimpleNamespace(detect_action=AsyncMock(return_value="work"),
                                         detect_danger=AsyncMock(return_value={"is_danger": False}))
        with patch.object(worker, "redis_client", redis), patch.object(worker, "analyzer", analyzer), patch.object(worker, "retriever", types.SimpleNamespace(get_context=lambda *_a, **_k: "rule")):
            worker.client_memory_cache = worker.FIFOSafeCache(100)
            await worker.process_job("video_frames", json.dumps({
                "client_id": "clock-test", "data": {"image": "test"},
                "_latency": {"version": 1, "frame_id": "f-2", "enqueued_redis_ms": 1000}}))
        analyzer.detect_danger.assert_awaited_once()
        self.assertEqual(redis.events[-1]["status"], "ok")
        self.assertNotIn("queue_age_ms", redis.events[-1]["timing"])


class ReportDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_report_payload_uses_session_metadata_and_excludes_image(self):
        import httpx
        received = []
        def handle(request):
            received.append(request)
            return httpx.Response(201, json={"ok": True})
        original_client = httpx.AsyncClient
        redis = FakeRedis()
        redis.hgetall = AsyncMock(return_value={"worksession_id": "17", "risk_type_id": "4", "video_path": "fixture://clip.mp4"})
        with patch.object(worker, "redis_client", redis), patch.object(worker, "DJANGO_API_URL", "https://report-test.invalid/api/incidents/"), patch.object(worker, "DJANGO_API_KEY", "fixture-key"), patch.object(worker.httpx, "AsyncClient", side_effect=lambda: original_client(transport=httpx.MockTransport(handle))):
            await worker.report_to_django("fixture-worker", "DANGER: test", "2026-10-22T00:00:00Z")
        self.assertEqual(len(received), 1)
        payload = json.loads(received[0].content)
        self.assertEqual(payload["worksession_id"], "17")
        self.assertEqual(payload["risk_type_id"], "4")
        self.assertEqual(payload["video_path"], "fixture://clip.mp4")
        self.assertEqual(payload["description"], "DANGER: test")
        self.assertNotIn("image", payload)
        self.assertEqual(received[0].headers["X-Internal-Key"], "fixture-key")

    async def test_report_rejection_and_timeout_only_log_without_retry(self):
        import httpx
        original_client = httpx.AsyncClient
        redis = FakeRedis()
        redis.hgetall = AsyncMock(return_value={})
        for failure in [404, 500, "timeout"]:
            received = []
            def handle(request):
                received.append(request)
                if failure == "timeout":
                    raise httpx.ReadTimeout("controlled timeout", request=request)
                return httpx.Response(failure, text="controlled rejection")
            with patch.object(worker, "redis_client", redis), patch.object(worker, "DJANGO_API_URL", "https://report-test.invalid/api/incidents/"), patch.object(worker.httpx, "AsyncClient", side_effect=lambda: original_client(transport=httpx.MockTransport(handle))), self.assertLogs(worker.logger, level="WARNING"):
                await worker.report_to_django("fixture-worker", "DANGER: test", "2026-10-22T00:00:00Z")
            self.assertEqual(len(received), 1)


class GatewayTests(unittest.TestCase):
    def test_real_websocket_contract_through_gateway_and_worker(self):
        redis = FakeRedis()
        redis.process = worker.process_job
        analyzer = types.SimpleNamespace(detect_action=AsyncMock(return_value="work"),
                                         detect_danger=AsyncMock(return_value={"is_danger": False}))
        with patch.object(gateway.redis, "from_url", return_value=redis), patch.object(worker, "redis_client", redis), patch.object(worker, "analyzer", analyzer), patch.object(worker, "retriever", types.SimpleNamespace(get_context=lambda *_a, **_k: "rule")), patch.object(gateway, "enforce_image_resolution", side_effect=lambda image, *_: image):
            worker.client_memory_cache = worker.FIFOSafeCache(100)
            with TestClient(gateway.app) as client:
                with client.websocket_connect("/ws/stream/contract-test") as ws:
                    ws.send_json({"type": "CONFIG", "latency_metrics": True})
                    ws.send_json({"type": "FRAME", "frame_id": "trace-1", "image": "fake-image",
                                  "_latency": {"gateway_prepare_ms": -100, "enqueued_redis_ms": 999999}})
                    result = ws.receive_json()
                    self.assertEqual(result["type"], "FRAME_RESULT")
                    self.assertEqual(result["frame_id"], "trace-1")
                    self.assertEqual(result["status"], "ok")
                    self.assertEqual(result["timing"]["queue_age_ms"], 10)
                    self.assertGreaterEqual(result["timing"]["gateway_prepare_ms"], 0)
                    self.assertNotIn("image", json.dumps(result))
                    self.assertNotIn("_latency", redis.jobs[0][1]["data"])


class SummaryTests(unittest.TestCase):
    def test_bounded_percentiles_and_disabled_mode(self):
        meter = PipelineLatency(enabled=True, window=20, interval_s=1e9)
        for number in range(1, 26):
            meter.record({"detector_ms": number, "bad": float("nan")})
        result = meter.snapshot()
        self.assertEqual(result["frames"], 25)
        self.assertEqual(result["metrics"]["detector_ms"], {"n": 20, "p50": 15, "p95": 24, "max": 25})
        self.assertNotIn("bad", result["metrics"])
        disabled = PipelineLatency(enabled=False)
        disabled.record({"detector_ms": 10})
        self.assertEqual(disabled.snapshot()["frames"], 0)


if __name__ == "__main__":
    unittest.main()
