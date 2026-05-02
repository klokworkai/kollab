from __future__ import annotations

from typing import AsyncIterator

from claude_agent_sdk import types as sdk_types
from claude_agent_sdk.client import ClaudeSDKClient

from .base import Agent, AgentChunk


class ClaudeAgent(Agent):
    name = "claude"

    def __init__(self, role: str, binary: str, model: str, workdir: str) -> None:
        self.role = role
        self._binary = binary
        self._model = model
        self._workdir = workdir
        self._client: ClaudeSDKClient | None = None
        self._session_id: str | None = None

    async def start(self, system_prompt: str, goal: str) -> None:
        options = sdk_types.ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=self._model,
            cwd=self._workdir,
            cli_path=self._binary,
            permission_mode="bypassPermissions",
        )
        self._client = ClaudeSDKClient(options=options)
        await self._client.connect()
        # deliver goal as first message; consume full response to warm up the session
        await self._client.query(goal)
        async for msg in self._client.receive_response():
            if isinstance(msg, sdk_types.ResultMessage):
                self._session_id = msg.session_id

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        if self._client is None:
            raise RuntimeError("ClaudeAgent.start() must be called before send()")
        await self._client.query(message)
        async for msg in self._client.receive_response():
            if isinstance(msg, sdk_types.StreamEvent):
                chunk = _chunk_from_stream_event(msg.event)
                if chunk:
                    yield chunk
            elif isinstance(msg, sdk_types.AssistantMessage):
                for block in msg.content:
                    if isinstance(block, sdk_types.TextBlock):
                        yield AgentChunk(kind="text", content=block.text)
                    elif isinstance(block, sdk_types.ThinkingBlock):
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
