from __future__ import annotations

import os
from typing import AsyncIterator

import openai

from ..config import ProviderConfig
from .base import Agent, AgentChunk


class ApiAgent(Agent):
    """OpenAI-compatible REST agent — covers DeepSeek, Groq, and plain OpenAI."""

    def __init__(self, role: str, provider: ProviderConfig, model: str) -> None:
        self.name = provider.id
        self.role = role
        self._provider = provider
        self._model = model
        self._history: list[dict] = []
        self._cancel: bool = False
        self._client: openai.AsyncOpenAI | None = None

    async def start(self, system_prompt: str, goal: str) -> None:
        api_key = os.environ.get(self._provider.api_key_env, "")
        self._client = openai.AsyncOpenAI(
            api_key=api_key or "placeholder",
            base_url=self._provider.api_base_url or None,
        )
        self._history = [{"role": "system", "content": system_prompt}]
        self._cancel = False

    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        if self._client is None:
            raise RuntimeError("ApiAgent.start() must be called before send()")
        self._cancel = False
        messages = self._history + [{"role": "user", "content": message}]
        full_response = ""
        tokens_in = 0
        tokens_out = 0

        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=messages,  # type: ignore[arg-type]
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            if self._cancel:
                break
            if chunk.usage:
                tokens_in = chunk.usage.prompt_tokens or 0
                tokens_out = chunk.usage.completion_tokens or 0
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    full_response += delta
                    yield AgentChunk(kind="text", content=delta)

        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": full_response})
        yield AgentChunk(
            kind="done",
            content=full_response,
            metadata={"tokens_in": tokens_in, "tokens_out": tokens_out},
        )

    async def stop(self) -> None:
        self._cancel = True  # abort any in-flight stream before clearing state
        self._history = []
        self._client = None

    async def interrupt(self) -> None:
        self._cancel = True
