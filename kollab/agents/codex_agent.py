from __future__ import annotations

import asyncio
import json
import re
from typing import AsyncIterator

from .base import Agent, AgentChunk

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class CodexAgent(Agent):
    name = "codex"

    def __init__(self, role: str, binary: str, model: str, workdir: str,
                 mcp_filesystem_enabled: bool = False,
                 mcp_filesystem_paths: list[str] | None = None,
                 mcp_github_enabled: bool = False,
                 mcp_github_token: str = "") -> None:
        self.role = role
        self._binary = binary
        self._model = model
        self._workdir = workdir
        self._mcp_filesystem_enabled = mcp_filesystem_enabled
        self._mcp_filesystem_paths = mcp_filesystem_paths or []
        self._mcp_github_enabled = mcp_github_enabled
        self._mcp_github_token = mcp_github_token
        self._session_id: str | None = None
        self._system_prompt: str = ""
        self._started: bool = False
        self._proc: asyncio.subprocess.Process | None = None

    async def start(self, system_prompt: str, goal: str) -> None:
        self._system_prompt = system_prompt
        self._started = False

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        if not self._started:
            message = f"{self._system_prompt}\n\n{message}"
            self._started = True
        async for chunk in self._run(message, new_session=self._session_id is None):
            yield chunk

    async def stop(self) -> None:
        # session_id intentionally preserved for halt/resume continuity.
        # If a subprocess is still running (e.g. session shutdown during a
        # turn), tear it down hard so we don't leak.
        await self._kill_proc()

    async def interrupt(self) -> None:
        """Cancel the in-flight turn by killing the subprocess.

        Codex's `exec` CLI has no in-band interrupt; SIGTERM the process and
        let the stdout pipe close so the receive loop in ACE drains naturally.
        Server-side thread state is preserved (we keep `_session_id`) so the
        next `codex exec resume` continues the conversation.
        """
        await self._kill_proc()

    async def _kill_proc(self) -> None:
        proc = self._proc
        if proc is None or proc.returncode is not None:
            return
        try:
            proc.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                return
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                pass

    async def _run(self, prompt: str, *, new_session: bool) -> AsyncIterator[AgentChunk]:
        cmd = self._build_cmd(prompt, new_session=new_session)
        import os as _os
        env = None
        if self._mcp_github_enabled and self._mcp_github_token:
            env = {**_os.environ, "GITHUB_TOKEN": self._mcp_github_token}
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None
        self._proc = proc

        text_buf: list[str] = []
        reasoning_buf: list[str] = []
        tokens_in = 0
        tokens_out = 0

        async for raw_line in proc.stdout:
            line = raw_line.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                yield AgentChunk(kind="text", content=line + "\n")
                text_buf.append(line)
                continue

            if self._session_id is None:
                sid = self._extract_session_id(event)
                if sid:
                    self._session_id = sid

            if event.get("type") == "turn.completed":
                usage = event.get("usage", {})
                tokens_in = usage.get("input_tokens", 0)
                tokens_out = usage.get("output_tokens", 0)

            kind, text = self._extract_item(event)
            if kind == "text":
                yield AgentChunk(kind="text", content=text)
                text_buf.append(text)
            elif kind == "reasoning":
                yield AgentChunk(kind="reasoning", content=text)
                reasoning_buf.append(text)

        await proc.wait()
        if self._proc is proc:
            self._proc = None
        yield AgentChunk(
            kind="done",
            content="".join(text_buf),
            metadata={"tokens_in": tokens_in, "tokens_out": tokens_out},
        )

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
        if event.get("type") == "thread.started":
            return event.get("thread_id")
        return None

    @staticmethod
    def _extract_item(event: dict) -> tuple[str, str]:
        """Return (kind, text) for item.completed events. kind is 'text' or 'reasoning'."""
        if event.get("type") == "item.completed":
            item = event.get("item", {})
            item_type = item.get("item_type") or item.get("type", "")
            text = item.get("text", "")
            if item_type == "agent_message" and text:
                return "text", text
            if item_type == "reasoning" and text:
                return "reasoning", text
        return "", ""
