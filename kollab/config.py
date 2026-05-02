from __future__ import annotations

import os
import shutil
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel

CONFIG_PATH = Path("~/.kollab/config.toml").expanduser()


class Config(BaseModel):
    claude_binary: str = "claude"
    claude_model: Literal["opus", "sonnet", "haiku"] = "sonnet"
    claude_workdir: str = "~/.kollab/workspace/claude"

    codex_binary: str = "codex"
    codex_model: str = "gpt-5.4"
    codex_workdir: str = "~/.kollab/workspace/codex"

    round_limit: int = 8
    port: int = 8765
    sessions_dir: str = "~/.kollab/sessions"


def _expand(value: str) -> str:
    return os.path.expanduser(value)


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        cfg = Config()
        save_config(cfg)
        return cfg
    with CONFIG_PATH.open("rb") as f:
        data = tomllib.load(f)
    return Config(**data)


def save_config(cfg: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("wb") as f:
        tomli_w.dump(cfg.model_dump(), f)


def validate_config(cfg: Config) -> list[str]:
    errors: list[str] = []
    for field, value in (("claude_binary", cfg.claude_binary), ("codex_binary", cfg.codex_binary)):
        resolved = _expand(value)
        if not (shutil.which(resolved) or (Path(resolved).is_file() and os.access(resolved, os.X_OK))):
            errors.append(f"{field}: '{value}' not found or not executable")
    return errors
