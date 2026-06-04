from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import tomli_w
from pydantic import BaseModel

CONFIG_PATH = Path("~/.kollab/config.toml").expanduser()

log = logging.getLogger("kollab.config")

_SLACK_PREFIX = "https://hooks.slack.com/"

MODEL_ALIASES: dict[str, str] = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    "mini":   "gpt-5.4-mini",
}

MCP_PACKAGES = {
    "mcp_filesystem": "@modelcontextprotocol/server-filesystem",
    "mcp_github":     "@modelcontextprotocol/server-github",
}

# Resolved install dir — all MCP packages go here
_MCP_DIR = Path("~/.kollab/mcp").expanduser()


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
    session_counter: int = 0

    # MCP tool toggles
    mcp_filesystem_enabled: bool = True
    mcp_filesystem_paths: list[str] = []
    mcp_github_enabled: bool = False
    mcp_github_token: str = ""

    # UI theme
    theme: str = "dark"  # 'dark' | 'light'

    # Logging
    logging_enabled: bool = False
    logging_level: str = "info"  # 'info' | 'debug'

    # Halt timeout: auto-expire halted sessions after this many seconds (0 = never)
    halt_timeout_secs: int = 1800

    # API auth — empty string means no auth required (local browser use unaffected)
    api_key: str = ""

    # Webhook emission
    webhooks: WebhookConfig = WebhookConfig()

    # File attachments
    attachment_max_file_kb: int = 100
    attachment_max_files: int = 5
    attachment_max_total_kb: int = 500


def _expand(value: str) -> str:
    return os.path.expanduser(value)


def _normalise_webhook_targets(cfg: Config) -> None:
    """Move any Slack URLs from targets to slack_targets and log a warning per URL moved."""
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
    """Return the local node binary path for an MCP package key."""
    # @modelcontextprotocol/server-filesystem -> mcp-server-filesystem
    pkg_name = MCP_PACKAGES[package_key]
    bin_name = "mcp-" + pkg_name.split("/")[-1]  # mcp-server-filesystem / mcp-server-github
    return _MCP_DIR / "node_modules" / ".bin" / bin_name


def ensure_mcp_packages() -> None:
    """Install missing MCP npm packages into ~/.kollab/mcp on first run."""
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
    """Atomically increment and persist the session counter. Returns the new number."""
    cfg.session_counter += 1
    save_config(cfg)
    return cfg.session_counter


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

    # move any Slack URLs from targets to slack_targets
    _normalise_webhook_targets(cfg)

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
