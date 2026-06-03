from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

# TODO: §4a — full Agent ABC + AgentChunk


@dataclass
class AgentChunk:
    kind: Literal["text", "reasoning", "done"]
    content: str
    metadata: dict | None = field(default=None)


class Agent(ABC):
    name: str
    role: str

    @abstractmethod
    async def start(self, system_prompt: str, goal: str) -> None:
        """Initialize session, set system prompt, deliver goal as first user message."""

    @abstractmethod
    async def send(self, message: str) -> AsyncIterator[AgentChunk]:
        """Send a message, yield chunks of the response as they arrive."""

    @abstractmethod
    async def stop(self) -> None:
        """Clean up the session."""

    async def interrupt(self) -> None:
        """Cancel the in-flight turn cleanly without tearing down the session."""
        return None

    @property
    def thread_id(self) -> str:
        """Provider-specific session/thread ID for resume continuity. Empty string if N/A."""
        return ""
