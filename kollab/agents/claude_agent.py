from __future__ import annotations

from typing import AsyncIterator

from claude_agent_sdk import types as sdk_types
from claude_agent_sdk.client import ClaudeSDKClient

from ..config import mcp_server_path
from .base import Agent, AgentChunk


class ClaudeAgent(Agent):
    name = "claude"

    def __init__(self, role: str, binary: str, model: str, workdir: str,
                 mcp_filesystem_enabled: bool = False,
                 mcp_filesystem_paths: list[str] | None = None) -> None:
        self.role = role
        self._binary = binary
        self._model = model
        self._workdir = workdir
        self._mcp_filesystem_enabled = mcp_filesystem_enabled
        self._mcp_filesystem_paths = mcp_filesystem_paths or []
        self._client: ClaudeSDKClient | None = None
        self._session_id: str | None = None

    async def start(self, system_prompt: str, goal: str) -> None:
        mcp_servers: dict = {}
        if self._mcp_filesystem_enabled:
            paths = self._mcp_filesystem_paths or [self._workdir]
            fs_bin = mcp_server_path("mcp_filesystem")
            if fs_bin.exists():
                mcp_servers["filesystem"] = {
                    "type": "stdio",
                    "command": "node",
                    "args": [str(fs_bin)] + paths,
                }
        options = sdk_types.ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=self._model,
            cwd=self._workdir,
            cli_path=self._binary,
            permission_mode="bypassPermissions",
            mcp_servers=mcp_servers if mcp_servers else {},
            include_partial_messages=True,
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        if self._client is None:
            raise RuntimeError("ClaudeAgent.start() must be called before send()")
        await self._client.query(message)
        _reasoning_streamed = False  # track whether thinking_delta chunks arrived
        async for msg in self._client.receive_response():
            if isinstance(msg, sdk_types.StreamEvent):
                chunk = _chunk_from_stream_event(msg.event)
                if chunk:
                    if chunk.kind == "reasoning":
                        _reasoning_streamed = True
                    yield chunk
            elif isinstance(msg, sdk_types.AssistantMessage):
                # include_partial_messages=True means text was already streamed
                # live via StreamEvent text_delta chunks. Only emit ThinkingBlock
                # here if reasoning did NOT already arrive via thinking_delta
                # stream events — when both paths fire the reasoning is duplicated.
                if not _reasoning_streamed:
                    for block in msg.content:
                        if isinstance(block, sdk_types.ThinkingBlock):
                            yield AgentChunk(kind="reasoning", content=block.thinking)
            elif isinstance(msg, sdk_types.ResultMessage):
                self._session_id = msg.session_id
                yield AgentChunk(
                    kind="done",
                    content="",
                    metadata={
                        "tokens_in": (msg.usage or {}).get("input_tokens"),
                        "tokens_out": (msg.usage or {}).get("output_tokens"),
                        "stop_reason": msg.stop_reason,
                        "session_id": msg.session_id,
                    },
                )

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.interrupt()
            except Exception:
                pass
            await self._client.disconnect()
            self._client = None

    async def interrupt(self) -> None:
        """Cancel the in-flight turn without tearing down the session."""
        if self._client is None:
            return
        try:
            await self._client.interrupt()
        except Exception:
            pass

    @property
    def thread_id(self) -> str:
        return self._session_id or ""


def _chunk_from_stream_event(event: dict) -> AgentChunk | None:
    if event.get("type") != "content_block_delta":
        return None
    delta = event.get("delta", {})
    delta_type = delta.get("type")
    if delta_type == "text_delta":
        text = delta.get("text", "")
        return AgentChunk(kind="text", content=text) if text else None
    if delta_type == "thinking_delta":
        thinking = delta.get("thinking", "")
        return AgentChunk(kind="reasoning", content=thinking) if thinking else None
    return None
