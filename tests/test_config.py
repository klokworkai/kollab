from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ensure package is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from kollab.config import Config, MODEL_ALIASES, load_config, save_config, validate_config


def test_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("kollab.config.CONFIG_PATH", config_file)

    cfg = Config(claude_binary="claude", port=9000, round_limit=4)
    save_config(cfg)

    assert config_file.exists()
    loaded = load_config()
    assert loaded.port == 9000
    assert loaded.round_limit == 4
    assert loaded.claude_binary == "claude"


def test_load_creates_defaults_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("kollab.config.CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.port == 8765
    assert config_file.exists()


def test_validate_bad_binary() -> None:
    cfg = Config(claude_binary="/nonexistent/claude", codex_binary="/nonexistent/codex")
    errors = validate_config(cfg)
    assert any("claude_binary" in e for e in errors)
    assert any("codex_binary" in e for e in errors)


def test_validate_good_binaries() -> None:
    cfg = Config(claude_binary="claude", codex_binary="codex")
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        errors = validate_config(cfg)
    assert errors == []


def test_claude_model_defaults_to_a_floating_alias() -> None:
    """Claude's --model accepts tier aliases the CLI itself resolves to its
    current model, so the default must be a bare alias, never a pinned
    snapshot string that can go stale."""
    cfg = Config()
    assert cfg.claude_model == "sonnet"
    assert MODEL_ALIASES["sonnet"] == "sonnet"


def test_codex_model_defaults_to_blank_for_account_default() -> None:
    """Codex has no alias resolution (`-m mini` is rejected outright, and a
    pinned snapshot degrades silently once retired), so the only value that
    can't go stale is omitting -m entirely — signaled by an empty string."""
    cfg = Config()
    assert cfg.codex_model == ""


def test_model_aliases_only_covers_claude_tiers() -> None:
    """Codex model strings must be passed through as-is (or left blank) since
    there is no safe fixed alias table to resolve them against."""
    assert set(MODEL_ALIASES) == {"haiku", "sonnet", "opus"}


def test_load_config_migrates_legacy_claude_snapshot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A config.toml written before kollab switched to floating tier aliases
    may still hold a pinned Claude snapshot string. It must be migrated to the
    matching tier on load so it keeps resolving to the CLI's current model."""
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("kollab.config.CONFIG_PATH", config_file)
    config_file.write_text('claude_model = "claude-sonnet-4-6"\n')

    loaded = load_config()
    assert loaded.claude_model == "sonnet"
