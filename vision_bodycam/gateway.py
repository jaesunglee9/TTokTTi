import asyncio
import base64
import io
import json
import logging
import os
import time
from latency import elapsed_ms, frame_id, redis_time_ms
from contextlib import asynccontextmanager
from typing import Any, Dict

import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
redis_client: redis.Redis | None = None

def enforce_image_resolution(b64_string: str, max_width=360, max_height=360) -> str:
    try:
        prefix = ""
        raw_b64 = b64_string
        if "," in b64_string:
            prefix, raw_b64 = b64_string.split(",", 1)
            prefix += ","

        image_data = base64.b64decode(raw_b64)
        image = Image.open(io.BytesIO(image_data))

        if image.width <= max_width and image.height <= max_height:
            return b64_string

        image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

        if image.mode in ("RGBA", "P"):
            image = image.convert("RGB")

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=80)
        
        optimized_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return prefix + optimized_b64

    except Exception as e:
        logger.error(f"Image Optimization Error: {e}")
        return b64_string 

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    logger.info("Connected to Redis pool.")
    yield
    await redis_client.aclose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/stream/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    logger.info(f"Client {client_id} connected.")

    pubsub = redis_client.pubsub()
    listener_task = None
    measure_latency = False
    session_metadata = {}
    await pubsub.subscribe(f"alerts:{client_id}")

    async def listen_for_results():
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    # --- [VINCI INTEGRATION] Gateway Streaming ---
                    # Now handles fragmented JSON streams seamlessly.
                    await websocket.send_text(message["data"])
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"PubSub Error for {client_id}: {e}")

    listener_task = asyncio.create_task(listen_for_results())

    try:
        while True:
            data_text = await websocket.receive_text()
            received_at = time.perf_counter()
            data_json: Dict[str, Any] = json.loads(data_text)
            # Internal timings must never come from the client.
            data_json.pop("_latency", None)
            
            msg_type = data_json.get("type", "").upper()
            if msg_type == "CONFIG":
                measure_latency = data_json.get("latency_metrics") is True
                mapping = {
                    "worksession_id": str(data_json.get("worksession_id", "")),
                    "risk_type_id": str(data_json.get("risk_type_id", "")),
                    "video_path": str(data_json.get("video_path", "")),
                    "access_token": str(data_json.get("access_token", ""))
                }
                session_metadata = {k: v for k, v in mapping.items() if k != "access_token"}
                # Store in Redis hash and set a 12-hour expiration
                await redis_client.hset(f"session_meta:{client_id}", mapping=mapping)
                await redis_client.expire(f"session_meta:{client_id}", 43200) 
                
                logger.info(f"Session configuration saved for {client_id}")
                continue # Skip the rest of the loop for this message
            # ----------------------------------------------

            b64_string = data_json.get("image")
            
            if b64_string:
                optimized_b64 = await asyncio.to_thread(
                    enforce_image_resolution, b64_string, 448, 448
                )
                data_json["image"] = optimized_b64

            job = {"client_id": client_id, "data": data_json, "session_meta": dict(session_metadata)}
            if measure_latency and msg_type == "FRAME" and frame_id(data_json.get("frame_id")):
                try:
                    job["_latency"] = {
                        "version": 1, "frame_id": data_json["frame_id"],
                        "gateway_prepare_ms": elapsed_ms(received_at),
                        "enqueued_redis_ms": await redis_time_ms(redis_client),
                    }
                except Exception:
                    logger.warning("Latency clock unavailable; frame processing continues")
            payload = json.dumps(job)

            if msg_type == "QUESTION":
                await redis_client.lpush("questions", payload)
                logger.info(f"Queued QUESTION for {client_id}")
            else:
                await redis_client.lpush("video_frames", payload)
                await redis_client.ltrim("video_frames", 0, 49) 

    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected.")
    except Exception as e:
        logger.error(f"WebSocket Error for {client_id}: {e}")    
    finally:
        if listener_task:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        await pubsub.unsubscribe(f"alerts:{client_id}")
        await pubsub.close()