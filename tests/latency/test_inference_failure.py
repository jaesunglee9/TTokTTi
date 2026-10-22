"""Test the real inference adapter with a stub model transport, never a live model."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]
openai = types.ModuleType("openai")
openai.AsyncOpenAI = lambda **_: types.SimpleNamespace(
    chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=AsyncMock())))
dotenv = types.ModuleType("dotenv")
dotenv.load_dotenv = lambda: None
spec = importlib.util.spec_from_file_location("tested_inference", ROOT / "vision_bodycam/core/inference.py")
adapter = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"openai": openai, "dotenv": dotenv}):
    spec.loader.exec_module(adapter)


class InferenceFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_transport_failure_is_not_a_safe_result(self):
        analyzer = adapter.SafetyAnalyzer()
        analyzer.client.chat.completions.create.side_effect = TimeoutError("test timeout")
        with self.assertRaisesRegex(RuntimeError, "Danger inference failed"):
            await analyzer.detect_danger(["test-image"], "rule")

    async def test_empty_response_is_not_a_safe_result(self):
        analyzer = adapter.SafetyAnalyzer()
        for content in ["", None]:
            analyzer.client.chat.completions.create.return_value = types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
            with self.assertRaisesRegex(RuntimeError, "Danger inference failed"):
                await analyzer.detect_danger(["test-image"], "rule")

    async def test_valid_safe_and_danger_results_are_preserved(self):
        analyzer = adapter.SafetyAnalyzer()
        for content, expected in [("SAFE", False), ("DANGER: missing helmet", True)]:
            analyzer.client.chat.completions.create.return_value = types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))])
            result = await analyzer.detect_danger(["test-image"], "rule")
            self.assertEqual(result["is_danger"], expected)


if __name__ == "__main__":
    unittest.main()
