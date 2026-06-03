from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# ensure package is importable from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from kollab.config import Config, ProviderConfig, load_config, save_config, validate_config


def test_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("kollab.config.CONFIG_PATH", config_file)

    cfg = Config(port=9000, round_limit=4)
    save_config(cfg)

    assert config_file.exists()
    loaded = load_config()
    assert loaded.port == 9000
    assert loaded.round_limit == 4
    assert len(loaded.providers) > 0


def test_load_creates_defaults_if_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_file = tmp_path / "config.toml"
    monkeypatch.setattr("kollab.config.CONFIG_PATH", config_file)

    cfg = load_config()
    assert cfg.port == 8765
    assert config_file.exists()


def test_validate_bad_binary() -> None:
    bad = ProviderConfig(id="bad", name="Bad", type="claude_sdk", binary="/nonexistent/claude", enabled=True)
    cfg = Config(providers=[bad])
    errors = validate_config(cfg)
    assert any("bad" in e for e in errors)


def test_validate_good_binaries() -> None:
    good = ProviderConfig(id="good", name="Good", type="claude_sdk", binary="claude", enabled=True)
    cfg = Config(providers=[good])
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        errors = validate_config(cfg)
    assert errors == []
