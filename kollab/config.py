from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel

CONFIG_PATH = Path("~/.kollab/config.toml").expanduser()


class Config(BaseModel):
    claude_binary: str = "claude"
    claude_model: str = "claude-sonnet-4-6"
    claude_workdir: str = "~/.kollab/workspace/claude"

    codex_binary: str = "codex"
    codex_model: str = "gpt-5.4"
    codex_workdir: str = "~/.kollab/workspace/codex"

    round_limit: int = 8
    max_tokens_per_turn: int | None = None
    max_tokens_per_session: int | None = None
    port: int = 8765
    sessions_dir: str = "~/.kollab/sessions"


def _expand(value: str) -> str:
    return os.path.expanduser(value)


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        cfg = Config()
        save_config(cfg)
    else:
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        cfg = Config(**data)
    
    # expand tildes on all path fields
    cfg.claude_workdir = _expand(cfg.claude_workdir)
    cfg.codex_workdir = _expand(cfg.codex_workdir)
    cfg.sessions_dir = _expand(cfg.sessions_dir)
    
    # auto-create working dirs
    Path(cfg.claude_workdir).mkdir(parents=True, exist_ok=True)
    Path(cfg.codex_workdir).mkdir(parents=True, exist_ok=True)
    Path(cfg.sessions_dir).mkdir(parents=True, exist_ok=True)
    
    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in cfg.model_dump().items() if v is not None}
    with CONFIG_PATH.open("wb") as f:
        tomli_w.dump(data, f)


def validate_config(cfg: Config) -> list[str]:
    errors: list[str] = []
    for field, value in (("claude_binary", cfg.claude_binary), ("codex_binary", cfg.codex_binary)):
        resolved = _expand(value)
        if not (shutil.which(resolved) or (Path(resolved).is_file() and os.access(resolved, os.X_OK))):
            errors.append(f"{field}: '{value}' not found or not executable")
    return errors
