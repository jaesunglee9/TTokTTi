# incident_review/backends.py
"""Model backends for the review/report stages.

CLI backends (Claude Code, Codex) are for offline experiments only: a personal
subscription must not serve production traffic. Production should implement
the same `complete()` signature on top of a paid API.
"""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Protocol

TIMEOUT_SECONDS = int(os.getenv("REVIEW_TIMEOUT_SECONDS", "240"))


class Backend(Protocol):
    name: str

    def complete(self, prompt: str, images: Optional[List[Path]] = None) -> str: ...


def extract_json(text: str) -> dict:
    """Take the last {...} block; models sometimes wrap JSON in prose or fences."""
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    candidates = fenced or re.findall(r"\{.*\}", text, re.S)
    if not candidates:
        raise ValueError("no JSON object in model output")
    return json.loads(candidates[-1])


class ClaudeCliBackend:
    """`claude -p` headless mode. Images are passed as paths the model reads with its Read tool."""

    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.name = f"claude-cli:{model or 'default'}"

    def complete(self, prompt: str, images: Optional[List[Path]] = None) -> str:
        images = images or []
        if images:
            listing = "\n".join(f"- {p.resolve()}" for p in images)
            prompt = f"Read each image file below with the Read tool before answering.\n{listing}\n\n{prompt}"
        cmd = ["claude", "-p", prompt, "--output-format", "json", "--allowedTools", "Read"]
        for d in sorted({str(p.resolve().parent) for p in images}):
            cmd += ["--add-dir", d]
        if self.model:
            cmd += ["--model", self.model]
        with tempfile.TemporaryDirectory() as cwd:  # keep project instructions out of the run
            out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
        if out.returncode != 0:
            raise RuntimeError(f"claude exited {out.returncode}: {out.stderr[-500:]}")
        payload = json.loads(out.stdout)
        if payload.get("is_error"):
            raise RuntimeError(f"claude error: {payload.get('result', '')[:500]}")
        return payload["result"]


class CodexCliBackend:
    """`codex exec` with images attached via -i, read-only sandbox."""

    def __init__(self, model: Optional[str] = None):
        self.model = model
        self.name = f"codex-cli:{model or 'default'}"

    def complete(self, prompt: str, images: Optional[List[Path]] = None) -> str:
        with tempfile.TemporaryDirectory() as cwd:
            last = Path(cwd) / "last.txt"
            cmd = ["codex", "exec", "--skip-git-repo-check", "-s", "read-only", "--output-last-message", str(last)]
            for p in images or []:
                cmd += ["-i", str(p.resolve())]
            if self.model:
                cmd += ["-m", self.model]
            cmd.append(prompt)
            out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT_SECONDS)
            if out.returncode != 0:
                raise RuntimeError(f"codex exited {out.returncode}: {out.stderr[-500:]}")
            return last.read_text(encoding="utf-8")


def make_backend(spec: str) -> Backend:
    kind, _, model = spec.partition(":")
    if kind == "claude":
        return ClaudeCliBackend(model or None)
    if kind == "codex":
        return CodexCliBackend(model or None)
    raise ValueError(f"unknown backend {spec!r}")
