"""Opt-in frame timings. No image, user, or model output is logged here."""
import math
import time


def elapsed_ms(start):
    return round((time.perf_counter() - start) * 1000, 3)


async def redis_time_ms(client):
    # Both gateway and worker use the SAME Redis clock, even on different hosts.
    seconds, micros = await client.time()
    return int(seconds) * 1000 + int(micros) / 1000


def frame_id(value):
    return value if isinstance(value, str) and 0 < len(value) <= 96 and value.isascii() and all(
        char.isalnum() or char in "-_." for char in value) else None


def valid_ms(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0


class FrameTiming:
    def __init__(self, metadata):
        self.started = time.perf_counter()
        self.metadata = metadata if isinstance(metadata, dict) else {}
        self.id = frame_id(self.metadata.get("frame_id"))
        self.enabled = self.metadata.get("version") == 1 and self.id is not None
        self.metrics = {}
        value = self.metadata.get("gateway_prepare_ms")
        if valid_ms(value):
            self.metrics["gateway_prepare_ms"] = value

    async def dequeue(self, client):
        stamp = self.metadata.get("enqueued_redis_ms")
        if self.enabled and valid_ms(stamp):
            age = await redis_time_ms(client) - stamp
            # A backwards Redis wall-clock jump is unavailable, never zero latency.
            if valid_ms(age):
                self.metrics["queue_age_ms"] = round(age, 3)

    def result(self, status):
        return {"type": "FRAME_RESULT", "frame_id": self.id, "status": status,
                "timing": {**self.metrics, "worker_total_ms": elapsed_ms(self.started)}}
