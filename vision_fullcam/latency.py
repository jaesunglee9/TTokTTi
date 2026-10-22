"""Bounded, opt-in software timings (not camera-to-photon latency)."""
import json
import math
import os
import time
from collections import deque


class PipelineLatency:
    def __init__(self, enabled=None, window=120, interval_s=10):
        self.enabled = os.getenv("TTOKTTI_LATENCY") == "1" if enabled is None else enabled
        self.window = window
        self.interval_s = interval_s
        self.values = {}
        self.frames = 0
        self.last_log = time.perf_counter()

    def record(self, metrics):
        if not self.enabled:
            return
        self.frames += 1
        for name, value in metrics.items():
            if math.isfinite(value) and value >= 0:
                self.values.setdefault(name, deque(maxlen=self.window)).append(value)
        if time.perf_counter() - self.last_log >= self.interval_s:
            self.flush()

    def snapshot(self):
        metrics = {}
        for name, values in self.values.items():
            values = sorted(values)
            def p(fraction):
                return round(values[max(0, math.ceil(len(values) * fraction) - 1)], 3)
            metrics[name] = {"n": len(values), "p50": p(.5), "p95": p(.95), "max": round(values[-1], 3)}
        return {"source": "fullcam_local", "window": self.window, "frames": self.frames, "metrics": metrics}

    def flush(self):
        if self.enabled and self.frames:
            print("[LATENCY] " + json.dumps(self.snapshot()), flush=True)
            self.last_log = time.perf_counter()
