from __future__ import annotations

from pathlib import Path

from ..config import Config, ProviderConfig
from .api_agent import ApiAgent
from .base import Agent
from .claude_agent import ClaudeAgent
from .codex_agent import CodexAgent
from .gemini_agent import GeminiAgent


def make_agent(provider: ProviderConfig, role: str, model_id: str, cfg: Config) -> Agent:
    """Instantiate the correct Agent subclass for the given provider."""
    workdir = Path(provider.workdir).expanduser().__str__() if provider.workdir else ""

    if provider.type == "claude_sdk":
        paths = [Path(p).expanduser().__str__() for p in cfg.mcp_filesystem_paths]
        return ClaudeAgent(
            role=role,
            binary=provider.binary,
            model=model_id,
            workdir=workdir or Path(cfg.sessions_dir).expanduser().__str__(),
            mcp_filesystem_enabled=cfg.mcp_filesystem_enabled and provider.mcp_enabled,
            mcp_filesystem_paths=paths,
        )

    if provider.type == "codex_cli":
        return CodexAgent(
            role=role,
            binary=provider.binary,
            model=model_id,
            workdir=workdir or Path(cfg.sessions_dir).expanduser().__str__(),
            mcp_filesystem_enabled=False,
            mcp_filesystem_paths=[],
        )

    if provider.type == "openai_api":
        return ApiAgent(role=role, provider=provider, model=model_id)

    if provider.type == "google_api":
        return GeminiAgent(role=role, provider=provider, model=model_id)

    raise ValueError(f"Unknown provider type: {provider.type!r}")
