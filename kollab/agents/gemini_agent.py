from __future__ import annotations

import os
from typing import AsyncIterator

from google import genai
from google.genai import types as genai_types

from ..config import ProviderConfig
from .base import Agent, AgentChunk


class GeminiAgent(Agent):
    """Google Gemini agent via the google-genai SDK."""

    def __init__(self, role: str, provider: ProviderConfig, model: str) -> None:
        self.name = provider.id
        self.role = role
        self._provider = provider
        self._model = model
        self._system_prompt: str = ""
        self._cancel: bool = False
        self._client: genai.Client | None = None
        self._chat: object | None = None  # google.genai Chat instance

    async def start(self, system_prompt: str, goal: str) -> None:
        api_key = os.environ.get(self._provider.api_key_env, "")
        self._client = genai.Client(api_key=api_key or "placeholder")
        self._system_prompt = system_prompt
        self._cancel = False
        self._chat = self._client.aio.chats.create(
            model=self._model,
            config=genai_types.GenerateContentConfig(
                system_instruction=system_prompt,
            ),
        )

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        if self._chat is None:
            raise RuntimeError("GeminiAgent.start() must be called before send()")
        self._cancel = False
        full_response = ""

        async for chunk in await self._chat.send_message_stream(message):  # type: ignore[union-attr]
            if self._cancel:
                break
            text = getattr(chunk, "text", None)
            if text:
                full_response += text
                yield AgentChunk(kind="text", content=text)

        yield AgentChunk(kind="done", content=full_response)

    async def stop(self) -> None:
        self._chat = None
        self._client = None

    async def interrupt(self) -> None:
        self._cancel = True
