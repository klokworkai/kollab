from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kollab.config import Config, WebhookConfig
from kollab.webhooks import _build_slack_payload, emit


def _make_cfg(
    enabled: bool = True,
    targets: list[str] | None = None,
    slack_targets: list[str] | None = None,
    events: list[str] | None = None,
    timeout_secs: int = 5,
) -> Config:
    wh = WebhookConfig(
        enabled=enabled,
        targets=targets or [],
        slack_targets=slack_targets or [],
        events=events if events is not None else [
            "session_start", "turn_end", "disagreement",
            "convergence", "round_limit", "halt",
            "directive", "session_end",
        ],
        timeout_secs=timeout_secs,
    )
    return Config(webhooks=wh)


def _mock_client(status: int = 200) -> tuple[MagicMock, MagicMock]:
    """Return (mock_client_instance, mock_response) with given status code."""
    mock_response = MagicMock()
    mock_response.status_code = status
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    return mock_client, mock_response


def _patch_httpx(mock_client: MagicMock):
    """Context manager that patches httpx.AsyncClient with the given mock instance."""
    patcher = patch("kollab.webhooks.httpx.AsyncClient")
    mock_cls = patcher.start()
    mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
    mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
    return patcher


# ------------------------------------------------------------------ disabled / filter

async def test_emit_disabled() -> None:
    cfg = _make_cfg(enabled=False, targets=["https://example.com/hook"])
    mock_client, _ = _mock_client()
    p = _patch_httpx(mock_client)
    try:
        await emit("turn_end", {"session_id": "s1"}, cfg)
        mock_client.post.assert_not_called()
    finally:
        p.stop()


async def test_emit_event_not_configured() -> None:
    cfg = _make_cfg(enabled=True, targets=["https://example.com/hook"], events=["session_start"])
    mock_client, _ = _mock_client()
    p = _patch_httpx(mock_client)
    try:
        await emit("turn_end", {"session_id": "s1"}, cfg)
        mock_client.post.assert_not_called()
    finally:
        p.stop()


# ------------------------------------------------------------------ standard payload shape

async def test_standard_payload_shape() -> None:
    cfg = _make_cfg(enabled=True, targets=["https://example.com/hook"])
    payload = {
        "event": "disagreement",
        "session_id": "sess_a1b2c3d4",
        "session_number": 12,
        "timestamp": "2026-05-18T21:04:32.118Z",
        "round": 3,
        "goal": "Design a retry policy",
        "turn_id": "X-2",
        "actor": "codex",
        "role": "critic",
        "verdict": "DISAGREE",
        "turn_text": "The proposed retry policy has no jitter",
    }
    mock_client, _ = _mock_client()
    p = _patch_httpx(mock_client)
    try:
        await emit("disagreement", payload, cfg)
        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        sent_json = call_kwargs[1]["json"]
        assert sent_json["session_id"] == "sess_a1b2c3d4"
        assert sent_json["session_number"] == 12
        assert sent_json["turn_id"] == "X-2"
        assert sent_json["verdict"] == "DISAGREE"
        assert sent_json["turn_text"] == "The proposed retry policy has no jitter"
    finally:
        p.stop()


# ------------------------------------------------------------------ Slack Block Kit shapes

def test_slack_payload_disagreement() -> None:
    payload = {
        "session_id": "sess_a1b2c3d4",
        "session_number": 12,
        "goal": "Design a retry policy",
        "round": 3,
        "turn_id": "X-2",
        "actor": "codex",
        "role": "critic",
        "verdict": "DISAGREE",
        "turn_text": "No jitter in the retry policy",
    }
    result = _build_slack_payload("disagreement", payload)
    assert "text" in result
    assert "kollab" in result["text"]
    assert "disagreement" in result["text"]
    blocks = result["blocks"]
    # header block
    assert blocks[0]["type"] == "header"
    assert "X-2" in blocks[0]["text"]["text"]
    # section with fields
    fields_text = " ".join(f["text"] for f in blocks[1]["fields"])
    assert "#12" in fields_text
    assert "sess_a1b2c3d4" in fields_text
    assert "DISAGREE" in fields_text
    # critique body
    assert "No jitter" in blocks[2]["text"]["text"]


def test_slack_payload_convergence() -> None:
    payload = {
        "session_id": "sess_x",
        "session_number": 5,
        "goal": "Review the caching strategy",
        "round": 3,
        "turn_id": "X-3",
        "actor": "codex",
        "verdict": "AGREE",
    }
    result = _build_slack_payload("convergence", payload)
    assert "convergence" in result["text"]
    blocks = result["blocks"]
    assert blocks[0]["type"] == "header"
    assert "Convergence" in blocks[0]["text"]["text"]
    fields_text = " ".join(f["text"] for f in blocks[1]["fields"])
    assert "#5" in fields_text
    assert "3" in fields_text  # rounds


def test_slack_payload_halt() -> None:
    payload = {
        "session_id": "sess_y",
        "session_number": 7,
        "goal": "Evaluate the auth design",
        "round": 2,
    }
    result = _build_slack_payload("halt", payload)
    assert "halted" in result["text"]
    blocks = result["blocks"]
    assert "Halted" in blocks[0]["text"]["text"]
    fields_text = " ".join(f["text"] for f in blocks[1]["fields"])
    assert "#7" in fields_text
    assert "2" in fields_text


# ------------------------------------------------------------------ Slack URL auto-detection

def test_slack_url_detection() -> None:
    from kollab.config import _normalise_webhook_targets, Config, WebhookConfig
    wh = WebhookConfig(
        enabled=True,
        targets=[
            "https://hooks.slack.com/services/T0001/B0001/xxxx",
            "https://myapp.com/webhook",
        ],
        slack_targets=[],
    )
    cfg = Config(webhooks=wh)
    _normalise_webhook_targets(cfg)
    assert "https://hooks.slack.com/services/T0001/B0001/xxxx" not in cfg.webhooks.targets
    assert "https://hooks.slack.com/services/T0001/B0001/xxxx" in cfg.webhooks.slack_targets
    assert "https://myapp.com/webhook" in cfg.webhooks.targets


# ------------------------------------------------------------------ delivery failure

async def test_delivery_failure_does_not_raise() -> None:
    cfg = _make_cfg(enabled=True, targets=["https://unreachable.example.com/hook"])
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
    p = _patch_httpx(mock_client)
    try:
        # Must not raise even if the target is unreachable
        await emit("turn_end", {"session_id": "s1", "round": 1}, cfg)
    finally:
        p.stop()


# ------------------------------------------------------------------ concurrent delivery

async def test_concurrent_delivery() -> None:
    cfg = _make_cfg(
        enabled=True,
        targets=["https://target1.example.com/hook", "https://target2.example.com/hook"],
    )
    mock_client, _ = _mock_client()
    p = _patch_httpx(mock_client)
    try:
        await emit("session_start", {"session_id": "s1", "round": 0, "goal": "test"}, cfg)
        assert mock_client.post.call_count == 2
        urls_called = {call[0][0] for call in mock_client.post.call_args_list}
        assert "https://target1.example.com/hook" in urls_called
        assert "https://target2.example.com/hook" in urls_called
    finally:
        p.stop()
