"""
kollab/webhooks.py — webhook emission layer

Fire-and-forget HTTP POST delivery for ACE session events.
Supports standard JSON targets and Slack incoming webhooks (Block Kit auto-shaped).

Implementation spec: specs/ace-api-webhooks.md sections 3–4.

Public interface (the only function ace.py and server.py should call):

    async def emit(event_type: str, payload: dict, cfg: Config) -> None

Status: pending implementation — stub only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config


async def emit(event_type: str, payload: dict, cfg: "Config") -> None:
    """
    Fire-and-forget webhook delivery.

    Delivers payload to all configured targets concurrently.
    Never raises — all errors are logged.

    Args:
        event_type: One of session_start, turn_end, disagreement, convergence,
                    round_limit, halt, directive, session_end.
        payload:    Dict containing all event fields. Must include at minimum:
                    session_id, session_number, timestamp, goal, round.
        cfg:        Current Config instance. Reads cfg.webhooks.* fields.
    """
    # TODO: implement per specs/ace-api-webhooks.md sections 3.1–4.1
    # 1. Return immediately if cfg.webhooks.enabled is False
    # 2. Return immediately if event_type not in cfg.webhooks.events
    # 3. Build standard JSON payload (already shaped by caller)
    # 4. Build Slack Block Kit payload for slack_targets
    # 5. POST to all targets concurrently via httpx.AsyncClient
    # 6. Log delivery failures at WARNING — never raise
    pass
