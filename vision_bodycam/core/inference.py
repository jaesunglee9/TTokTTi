# vision_bodycam/core/inference.py

import os
import logging
from typing import Dict, Any, List, AsyncGenerator
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()
logger = logging.getLogger(__name__)

VLLM_URL = os.getenv("VLLM_URL", "http://localhost:8889/v1")

class SafetyAnalyzer:
    def __init__(self, api_url: str = VLLM_URL):
        # We use the OpenAI-compatible client to talk to vLLM
        self.client = AsyncOpenAI(base_url=api_url, api_key="EMPTY")
        self.model_name = "cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit" # Must match vllm serve argument

    def _format_image_url(self, image_b64: str) -> str:
        """Ensures the base64 string has the correct prefix exactly once."""
        if image_b64.startswith("data:image"):
            return image_b64
        return f"data:image/jpeg;base64,{image_b64}"

    def _build_multi_frame_content(self, text_prompt: str, frames: List[str]) -> List[Dict[str, Any]]:
        """
        [VINCI INTEGRATION] Multi-Frame Prompting 
        Builds the payload stacking multiple chronological frames for vLLM natively.
        """
        content = [{"type": "text", "text": text_prompt}]
        for b64 in frames:
            content.append({
                "type": "image_url", 
                "image_url": {"url": self._format_image_url(b64)}
            })
        return content

    async def detect_danger(self, frames: List[str], rag_context: str) -> Dict[str, Any]:
        """
        Fast Loop (Blocking): Standard non-streaming safety check over recent frames.
        """
        try:
            prompt = (
                f"Safety Rules Context: {rag_context}\n"
                "You are a safety inspector viewing the last 3 seconds of a worker's bodycam. "
                "Is the worker wearing required safety gear or performing a safe action? "
                "If there is a safety violation, you MUST start your response exactly with 'DANGER:' followed by a brief 1-sentence explanation of the hazard. "
                "If everything is safe, reply only with 'SAFE'."
            )

            # NOTE: If you ever want to test pure scene description, you can temporarily 
            # swap `prompt` for `prompt_debug` in the completions call below.
            prompt_debug = (
                f"Safety Rules Context: {rag_context}\n"
                "You are viewing the last 3 seconds of a worker's bodycam. "
                "Describe the current situation, based on the video and the context."    
            )

            logger.info(f"[vLLM REQUEST] detect_danger | Checking {len(frames)} frames against RAG context: '{rag_context}'")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{
                    "role": "user", 
                    "content": self._build_multi_frame_content(prompt, frames)}],
                temperature=0.1, 
                max_tokens=100,
                stream=False # Explicitly Blocking
            )

            message = response.choices[0].message
            result_text = message.content[0].get("text", "").strip() if isinstance(message.content, list) else str(message.content).strip()

            # DEBUG LOGGING: Print exactly what vLLM spat out
            logger.info(f"[vLLM OUTPUT] detect_danger | {result_text}")

            if not result_text or message.content is None:
                raise ValueError("Danger inference returned no result")

            return {"is_danger": result_text.upper().startswith("DANGER"), "details": result_text}

        except Exception as e:
            logger.error(f"Inference Error in detect_danger: {e}")
            # Propagate to the worker: unavailable inference is not a successful
            # safe frame, and must not contaminate successful latency percentiles.
            raise RuntimeError("Danger inference failed") from e

    async def detect_action(self, frames: List[str]) -> str:
        """Slow Loop (Blocking): Determines broad action context from recent frames."""
        try:
            prompt = "In two words or less, what physical task is the worker performing across these frames?"
            
            logger.info(f"[vLLM REQUEST] detect_action | Analyzing {len(frames)} frames...")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": self._build_multi_frame_content(prompt, frames)}],
                temperature=0.1,
                max_tokens=10,
                stream=False
            )

            message = response.choices[0].message
            result_text = message.content[0].get("text", "").strip() if isinstance(message.content, list) else str(message.content).strip()
            
            # DEBUG LOGGING: Print the recognized action
            logger.info(f"[vLLM OUTPUT] detect_action | Recognized Action: '{result_text}'")

            return result_text

        except Exception as e:
            logger.error(f"Action Detection Error: {e}")
            return "general work"

    async def compress_memory(self, memory_history: List[Dict[str, Any]]) -> str:
        """
        [VINCI INTEGRATION] Memory Compression Algorithm
        Extracts core features from short-term memory to compress and store in long-term memory.
        """
        try:
            if not memory_history:
                return "No prior context."
                
            history_text = "\n".join([f"[{m.get('timestamp', '')}] Action: {m.get('action', '')} | Result: {m.get('observation', '')}" for m in memory_history])
            prompt = (
                "Summarize the following chronological sequence of a worker's actions and observations into a concise, 1-2 sentence long-term memory summary.\n"
                "Focus ONLY on the core context and persistent state.\n"
                f"History:\n{history_text}"
            )
            
            logger.info(f"[vLLM REQUEST] compress_memory | Compressing {len(memory_history)} short-term memory items...")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                temperature=0.1,
                max_tokens=60,
                stream=False
            )

            message = response.choices[0].message
            result_text = message.content[0].get("text", "").strip() if isinstance(message.content, list) else str(message.content).strip()
            
            logger.info(f"[vLLM OUTPUT] compress_memory | Compressed: '{result_text}'")
            return result_text

        except Exception as e:
            logger.error(f"Memory Compression Error: {e}")
            return "Failed to compress memory."

    async def answer_question(self, frames: List[str], question: str, recent_context: str) -> AsyncGenerator[str, None]:
        """
        Asynchronous streaming via AsyncOpenAI to yield text chunks immediately.
        """
        try:
            prompt = (
                f"Recent Event History Timeline:\n{recent_context}\n"
                "You are an egocentric AI assistant analyzing the user's view in real time. "
                f"User Question: {question}\n"
                "Provide a clear, conversational answer directly addressing the user based on the timeline and chronological frames."
            )
            
            logger.info(f"[vLLM REQUEST] answer_question | Streaming answer for: '{question}'")

            response = await self.client.chat.completions.create(
                model=self.model_name,
                messages=[{
                    "role": "user", 
                    "content": self._build_multi_frame_content(prompt, frames)}],
                temperature=0.4,
                max_tokens=150,
                stream=True # Mixed streaming toggled ON
            )

            full_answer = ""
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    chunk_text = chunk.choices[0].delta.content
                    full_answer += chunk_text
                    yield chunk_text
            
            # DEBUG LOGGING: Log the fully constructed answer once the stream ends
            logger.info(f"[vLLM OUTPUT] answer_question COMPLETE | {full_answer}")

        except Exception as e:
            logger.error(f"Inference Error in answer_question: {e}")
            yield "I'm having trouble analyzing the scene right now."
   

# Global instance to be used by main.py
# We instantiate it as None first, then load it on startup event
analyzer_instance = None