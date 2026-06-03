from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, ConfigDict, Field

CONFIG_PATH = Path("~/.kollab/config.toml").expanduser()

log = logging.getLogger("kollab.config")

_SLACK_PREFIX = "https://hooks.slack.com/"

MCP_PACKAGES = {
    "mcp_filesystem": "@modelcontextprotocol/server-filesystem",
    "mcp_github":     "@modelcontextprotocol/server-github",
}

_MCP_DIR = Path("~/.kollab/mcp").expanduser()


# ------------------------------------------------------------------ provider models

class ProviderModel(BaseModel):
    alias: str     # short name shown in UI: "sonnet", "flash"
    model_id: str  # full model string sent to the API


class ProviderConfig(BaseModel):
    id: str
    name: str
    type: Literal["claude_sdk", "codex_cli", "openai_api", "google_api"]
    models: list[ProviderModel] = []
    binary: str = ""           # CLI providers: path to executable
    auth_method: Literal["cli_oauth", "env_var"] = "env_var"
    api_key_env: str = ""      # env var that holds the API key
    api_base_url: str = ""     # OpenAI-compatible providers
    mcp_enabled: bool = False
    workdir: str = ""
    enabled: bool = True


def _default_providers() -> list[ProviderConfig]:
    return [
        ProviderConfig(
            id="anthropic", name="Anthropic (Claude)", type="claude_sdk",
            binary="claude", auth_method="cli_oauth", mcp_enabled=True,
            workdir="~/.kollab/workspace/claude", enabled=True,
            models=[
                ProviderModel(alias="haiku",  model_id="claude-haiku-4-5-20251001"),
                ProviderModel(alias="sonnet", model_id="claude-sonnet-4-6"),
                ProviderModel(alias="opus",   model_id="claude-opus-4-7"),
            ],
        ),
        ProviderConfig(
            id="openai", name="OpenAI (Codex)", type="codex_cli",
            binary="codex", auth_method="cli_oauth", mcp_enabled=False,
            workdir="~/.kollab/workspace/codex", enabled=True,
            models=[
                ProviderModel(alias="mini",    model_id="gpt-5.4-mini"),
                ProviderModel(alias="gpt-5.4", model_id="gpt-5.4"),
                ProviderModel(alias="gpt-5.5", model_id="gpt-5.5"),
            ],
        ),
        ProviderConfig(
            id="deepseek", name="DeepSeek", type="openai_api",
            auth_method="env_var", api_key_env="DEEPSEEK_API_KEY",
            api_base_url="https://api.deepseek.com/v1",
            mcp_enabled=False, workdir="", enabled=False,
            models=[
                ProviderModel(alias="flash", model_id="deepseek-v4-flash"),
                ProviderModel(alias="pro",   model_id="deepseek-v4-pro"),
            ],
        ),
        ProviderConfig(
            id="groq", name="Groq", type="openai_api",
            auth_method="env_var", api_key_env="GROQ_API_KEY",
            api_base_url="https://api.groq.com/openai/v1",
            mcp_enabled=False, workdir="", enabled=False,
            models=[
                ProviderModel(alias="llama4", model_id="llama-4-70b"),
            ],
        ),
        ProviderConfig(
            id="gemini", name="Google (Gemini)", type="google_api",
            auth_method="env_var", api_key_env="GOOGLE_API_KEY",
            mcp_enabled=False, workdir="", enabled=False,
            models=[
                ProviderModel(alias="pro",   model_id="gemini-3.1-pro"),
                ProviderModel(alias="flash", model_id="gemini-3.1-flash"),
            ],
        ),
    ]


# ------------------------------------------------------------------ webhook config

class WebhookConfig(BaseModel):
    enabled: bool = False
    targets: list[str] = []
    slack_targets: list[str] = []
    events: list[str] = [
        "session_start", "turn_end", "disagreement",
        "convergence", "round_limit", "halt",
        "directive", "session_end",
    ]
    timeout_secs: int = 5


# ------------------------------------------------------------------ main config

class Config(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: list[ProviderConfig] = Field(default_factory=_default_providers)

    round_limit: int = 8
    max_tokens_per_turn: int | None = None
    max_tokens_per_session: int | None = None
    port: int = 8765
    sessions_dir: str = "~/.kollab/sessions"
    session_counter: int = 0

    mcp_filesystem_enabled: bool = True
    mcp_filesystem_paths: list[str] = []
    mcp_github_enabled: bool = False
    mcp_github_token: str = ""

    theme: str = "dark"
    logging_enabled: bool = False
    logging_level: str = "info"
    halt_timeout_secs: int = 1800
    api_key: str = ""

    webhooks: WebhookConfig = Field(default_factory=WebhookConfig)


# ------------------------------------------------------------------ helpers

def _expand(value: str) -> str:
    return os.path.expanduser(value)


def _normalise_webhook_targets(cfg: Config) -> None:
    moved = [u for u in cfg.webhooks.targets if u.startswith(_SLACK_PREFIX)]
    if not moved:
        return
    cfg.webhooks.targets = [u for u in cfg.webhooks.targets if not u.startswith(_SLACK_PREFIX)]
    cfg.webhooks.slack_targets = list(cfg.webhooks.slack_targets) + moved
    for u in moved:
        log.warning(
            "webhook target '%s' moved to slack_targets (Slack requires Block Kit format)", u
        )


def mcp_server_path(package_key: str) -> Path:
    pkg_name = MCP_PACKAGES[package_key]
    bin_name = "mcp-" + pkg_name.split("/")[-1]
    return _MCP_DIR / "node_modules" / ".bin" / bin_name


def ensure_mcp_packages() -> None:
    npm = shutil.which("npm")
    if not npm:
        print("[kollab] WARNING: npm not found — MCP tools will not be available.",
              file=sys.stderr)
        return

    _MCP_DIR.mkdir(parents=True, exist_ok=True)
    to_install: list[str] = []

    for key, pkg in MCP_PACKAGES.items():
        bin_path = mcp_server_path(key)
        if not bin_path.exists():
            to_install.append(pkg)

    if not to_install:
        return

    print(f"[kollab] Installing MCP packages: {', '.join(to_install)} …",
          file=sys.stderr, flush=True)
    result = subprocess.run(
        [npm, "install", "--prefix", str(_MCP_DIR),
         "--save", "--no-fund", "--loglevel=error"] + to_install,
        capture_output=False,
    )
    if result.returncode != 0:
        print("[kollab] WARNING: npm install failed — MCP tools may not work.",
              file=sys.stderr)
    else:
        print("[kollab] MCP packages ready.", file=sys.stderr, flush=True)


def next_session_number(cfg: Config) -> int:
    cfg.session_counter += 1
    save_config(cfg)
    return cfg.session_counter


def provider_is_ready(provider: ProviderConfig) -> tuple[bool, str]:
    """Check if a provider can be used. Returns (is_ready, message)."""
    if provider.type in ("claude_sdk", "codex_cli"):
        binary = _expand(provider.binary) if provider.binary else ""
        if binary and (shutil.which(binary) or
                       (Path(binary).is_file() and os.access(binary, os.X_OK))):
            return True, "binary found"
        return False, f"binary '{provider.binary}' not found"
    if provider.type in ("openai_api", "google_api"):
        if not provider.api_key_env:
            return False, "no api_key_env configured"
        if os.environ.get(provider.api_key_env, ""):
            return True, f"{provider.api_key_env} is set"
        return False, f"{provider.api_key_env} not set in environment"
    return False, "unknown provider type"


# ------------------------------------------------------------------ migration

def _migrate_if_needed(data: dict) -> tuple[dict, bool]:
    """Detect old flat config shape and convert to provider registry. Returns (data, migrated)."""
    if "providers" in data:
        return data, False

    log.info("Migrating config from old flat format to provider registry")
    defaults = _default_providers()

    claude_binary = data.pop("claude_binary", "claude")
    claude_workdir = data.pop("claude_workdir", "~/.kollab/workspace/claude")
    data.pop("claude_model", None)

    codex_binary = data.pop("codex_binary", "codex")
    codex_workdir = data.pop("codex_workdir", "~/.kollab/workspace/codex")
    data.pop("codex_model", None)

    provider_dicts: list[dict] = []
    for p in defaults:
        pd = p.model_dump()
        if p.id == "anthropic":
            pd["binary"] = claude_binary
            pd["workdir"] = claude_workdir
        elif p.id == "openai":
            pd["binary"] = codex_binary
            pd["workdir"] = codex_workdir
        provider_dicts.append(pd)

    data["providers"] = provider_dicts
    return data, True


# ------------------------------------------------------------------ load / save

def load_config() -> Config:
    if not CONFIG_PATH.exists():
        cfg = Config()
        save_config(cfg)
    else:
        with CONFIG_PATH.open("rb") as f:
            data = tomllib.load(f)
        data, was_migrated = _migrate_if_needed(data)
        cfg = Config(**data)
        if was_migrated:
            save_config(cfg)

    cfg.sessions_dir = _expand(cfg.sessions_dir)
    for p in cfg.providers:
        if p.workdir:
            p.workdir = _expand(p.workdir)

    _normalise_webhook_targets(cfg)

    Path(cfg.sessions_dir).mkdir(parents=True, exist_ok=True)
    for p in cfg.providers:
        if p.workdir and p.enabled:
            Path(p.workdir).mkdir(parents=True, exist_ok=True)

    return cfg


def save_config(cfg: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = cfg.model_dump(exclude_none=True)
    with CONFIG_PATH.open("wb") as f:
        tomli_w.dump(data, f)


def validate_config(cfg: Config) -> list[str]:
    errors: list[str] = []
    for p in cfg.providers:
        if p.enabled and p.type in ("claude_sdk", "codex_cli") and not p.binary:
            errors.append(f"Provider '{p.id}' is enabled but has no binary configured")
    return errors
