from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator

from .base import Agent, AgentChunk

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Event types emitted by `codex exec --json` that carry text the user should see.
# Anything not listed here is silently consumed (tool calls, sandbox events, etc.).
_TEXT_KINDS = {"message", "assistant_message", "output", "text"}


class CodexAgent(Agent):
    name = "codex"

    def __init__(self, role: str, binary: str, model: str, workdir: str) -> None:
        self.role = role
        self._binary = binary
        self._model = model
        self._workdir = workdir
        self._session_id: str | None = None

    async def start(self, system_prompt: str, goal: str) -> None:
        """Deliver system prompt + goal as the first message to start the session."""
        first_message = f"{system_prompt}\n\n{goal}"
        # consume the full response and capture the session ID
        async for _ in self._run(first_message, new_session=True):
            pass

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        async for chunk in self._run(message, new_session=False):
            yield chunk

    async def stop(self) -> None:
        # codex sessions are stateless between invocations; nothing to tear down
        self._session_id = None

    async def _run(self, prompt: str, *, new_session: bool) -> AsyncIterator[AgentChunk]:
        cmd = self._build_cmd(prompt, new_session=new_session)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        assert proc.stdout is not None

        text_buf: list[str] = []
        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # plain text fallback — codex printed something non-JSON
                yield AgentChunk(kind="text", content=line + "\n")
                text_buf.append(line)
                continue

            # capture session ID from whichever event exposes it
            if self._session_id is None:
                sid = self._extract_session_id(event)
                if sid:
                    self._session_id = sid

            text = self._extract_text(event)
            if text:
                yield AgentChunk(kind="text", content=text)
                text_buf.append(text)

        await proc.wait()
        yield AgentChunk(kind="done", content="".join(text_buf))

    def _build_cmd(self, prompt: str, *, new_session: bool) -> list[str]:
        if new_session or self._session_id is None:
            return [
                self._binary, "exec",
                "--json",
                "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox",
                "-m", self._model,
                "-C", self._workdir,
                prompt,
            ]
        return [
            self._binary, "exec", "resume",
            self._session_id,
            "--json",
            "--skip-git-repo-check",
            "--dangerously-bypass-approvals-and-sandbox",
            prompt,
        ]

    @staticmethod
    def _extract_session_id(event: dict) -> str | None:
        for key in ("session_id", "id", "sessionId"):
            val = event.get(key)
            if isinstance(val, str) and _UUID_RE.fullmatch(val):
                return val
        # deep scan: some CLIs nest the id
        for val in event.values():
            if isinstance(val, str) and _UUID_RE.fullmatch(val):
                return val
        return None

    @staticmethod
    def _extract_text(event: dict) -> str:
        kind = event.get("type", "")
        if kind in _TEXT_KINDS:
            for key in ("content", "text", "message", "delta"):
                val = event.get(key)
                if isinstance(val, str) and val:
                    return val
                if isinstance(val, list):
                    parts = [p.get("text", "") for p in val if isinstance(p, dict)]
                    text = "".join(parts)
                    if text:
                        return text
        return ""
