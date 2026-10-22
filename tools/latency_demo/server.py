"""Serve the demo UI and reuse the project's actual WebSocket Gateway."""
import json
import os
import sys
from pathlib import Path
from fastapi.responses import FileResponse, JSONResponse
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "vision_bodycam"))
import gateway
app = gateway.app
HERE = Path(__file__).parent

@app.get("/")
def index():
    return FileResponse(HERE / "index.html")
@app.get("/app.js")
def script():
    return FileResponse(HERE / "app.js", media_type="text/javascript")
@app.get("/demo/status")
async def status():
    value = await gateway.redis_client.get("latency_demo:worker")
    return json.loads(value) if value else {"ready": False, "reason": "모델을 준비하고 있습니다."}
@app.get("/demo/sample.jpg")
def sample():
    path = Path(os.getenv("DEMO_SAMPLE", "/tmp/ttoktti-runtime/sample.jpg"))
    if not path.exists():
        return JSONResponse({"error": "Sample unavailable; upload your own image"}, status_code=404)
    return FileResponse(path, media_type="image/jpeg")

@app.get("/memory")
def memory_report():
    return FileResponse(HERE / "memory-report.html")
@app.get("/demo/memory-results.json")
def memory_results():
    return FileResponse(ROOT / "performance-results/memory-video-20261022.json", media_type="application/json")
@app.get("/demo/memory-video.mp4")
def memory_video():
    return FileResponse("/tmp/ttoktti-runtime/memory-benchmark/source.mp4", media_type="video/mp4")
@app.get("/demo/memory-report.md")
def memory_report_markdown():
    return FileResponse(ROOT / "docs/memory-video-benchmark.md", media_type="text/plain; charset=utf-8")
