from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import AsyncIterator

from .base import Agent, AgentChunk

log = logging.getLogger("kollab.codex_agent")

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


class CodexAgent(Agent):
    name = "codex"

    def __init__(self, role: str, binary: str, model: str, workdir: str,
                 mcp_filesystem_enabled: bool = False,
                 mcp_filesystem_paths: list[str] | None = None,
                 mcp_github_enabled: bool = False,
                 mcp_github_token: str = "",
                 reasoning_effort: str = "") -> None:
        self.role = role
        self._binary = binary
        self._model = model
        self._reasoning_effort = reasoning_effort
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

    async def send(self, message: str, *, images: list | None = None) -> AsyncIterator[AgentChunk]:
        if not self._started:
            message = f"{self._system_prompt}\n\n{message}"
            self._started = True
        async for chunk in self._run(message, new_session=self._session_id is None, images=images):
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

    async def _run(self, prompt: str, *, new_session: bool, images: list | None = None) -> AsyncIterator[AgentChunk]:
        cmd = self._build_cmd(prompt, new_session=new_session, images=images or [])
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

        stderr_buf: list[bytes] = []

        async def _drain_stderr() -> None:
            # Read concurrently with stdout, not after — otherwise a chatty
            # stderr can fill its OS pipe buffer and deadlock the process
            # while we're only reading stdout.
            assert proc.stderr is not None
            async for chunk in proc.stderr:
                stderr_buf.append(chunk)

        stderr_task = asyncio.create_task(_drain_stderr())

        text_buf: list[str] = []
        reasoning_buf: list[str] = []
        tokens_in = 0
        tokens_out = 0
        agent_error: str | None = None

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
            elif event.get("type") == "turn.failed":
                # Codex reports failures (bad model, API errors, etc.) as a
                # JSON event on stdout, not a stderr message or non-zero
                # exit — confirmed: `-m <invalid>` exits 0 with this event
                # and empty agent output, easy to mistake for a silent hang.
                agent_error = event.get("error", {}).get("message") or str(event)
                log.warning("codex turn.failed: %s", agent_error)

            item = event.get("item", {})
            if item.get("item_type") == "error":
                agent_error = item.get("text") or item.get("message") or str(item)
                log.warning("codex item error: %s", agent_error)

            kind, text = self._extract_item(event)
            if kind == "text":
                yield AgentChunk(kind="text", content=text)
                text_buf.append(text)
            elif kind == "reasoning":
                yield AgentChunk(kind="reasoning", content=text)
                reasoning_buf.append(text)

        await proc.wait()
        await stderr_task
        if self._proc is proc:
            self._proc = None
        if proc.returncode != 0 or not text_buf:
            stderr_text = b"".join(stderr_buf).decode("utf-8", errors="replace").strip()
            agent_error = agent_error or stderr_text or f"codex exec exited {proc.returncode} with no output"
            log.warning(
                "codex exec exited %s with no usable output — cmd=%s stderr=%s",
                proc.returncode, cmd, stderr_text or "(empty)",
            )
        yield AgentChunk(
            kind="done",
            content="".join(text_buf),
            metadata={"tokens_in": tokens_in, "tokens_out": tokens_out, "error": agent_error},
        )

    def _add_dir_flags(self) -> list[str]:
        if not self._mcp_filesystem_enabled:
            return []
        flags: list[str] = []
        for p in self._mcp_filesystem_paths:
            flags += ["--add-dir", p]
        return flags

    def _build_cmd(self, prompt: str, *, new_session: bool, images: list | None = None) -> list[str]:
        img_flags: list[str] = []
        for p in (images or []):
            img_flags += ["-i", str(p)]

        if new_session or self._session_id is None:
            # Empty model means "let Codex resolve its own current account
            # default" rather than pinning a snapshot string that can go
            # stale — see DEFAULT_CODEX_MODEL in config.py.
            model = self._model.strip()
            model_flags = ["-m", model] if model else []
            # Reasoning effort only makes sense pinned to an explicit model —
            # if model is blank (account default), leave Codex's defaults alone end to end.
            reasoning_flags = (
                ["-c", f"model_reasoning_effort={self._reasoning_effort}"]
                if model and self._reasoning_effort else []
            )
            return [
                self._binary, "exec",
                "--json",
                "--skip-git-repo-check",
                "--approve-for-me",
                *self._add_dir_flags(),
                *model_flags,
                *reasoning_flags,
                "-C", self._workdir,
                *img_flags,
                prompt,
            ]
        # `codex exec resume` accepts neither --approve-for-me/--sandbox nor
        # --add-dir (confirmed: both error with "unexpected argument") — the
        # resumed thread keeps the approval/sandbox policy and directory
        # access set when it was created via the branch above.
        return [
            self._binary, "exec", "resume",
            self._session_id,
            "--json",
            "--skip-git-repo-check",
            *img_flags,
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
