from __future__ import annotations

import asyncio
import logging

import httpx

from .config import Config

log = logging.getLogger("kollab.webhooks")

_SLACK_PREFIX = "https://hooks.slack.com/"
_SLACK_TEXT_LIMIT = 500


async def emit(event_type: str, payload: dict, cfg: Config) -> None:
    """Fire-and-forget webhook delivery. Never raises."""
    if not cfg.webhooks.enabled:
        return
    if event_type not in cfg.webhooks.events:
        return
    targets = list(cfg.webhooks.targets)
    slack_targets = list(cfg.webhooks.slack_targets)
    if not targets and not slack_targets:
        return

    slack_payload = _build_slack_payload(event_type, payload)

    async with httpx.AsyncClient(timeout=cfg.webhooks.timeout_secs) as client:
        coros = (
            [_post(client, url, payload) for url in targets]
            + [_post(client, url, slack_payload) for url in slack_targets]
        )
        results = await asyncio.gather(*coros, return_exceptions=True)
        all_urls = targets + slack_targets
        for url, result in zip(all_urls, results):
            if isinstance(result, Exception):
                log.warning("webhook delivery failed url=%s error=%s", url, result)


async def _post(client: httpx.AsyncClient, url: str, payload: dict) -> None:
    resp = await client.post(url, json=payload)
    if not (200 <= resp.status_code < 300):
        log.warning("webhook non-2xx url=%s status=%d", url, resp.status_code)


def _trunc(text: str) -> str:
    if len(text) > _SLACK_TEXT_LIMIT:
        return text[:_SLACK_TEXT_LIMIT] + "…"
    return text


def _build_slack_payload(event_type: str, payload: dict) -> dict:
    sid = payload.get("session_id", "")
    snum = payload.get("session_number", 0)
    goal = payload.get("goal", "")
    round_ = payload.get("round", 0)
    turn_id = payload.get("turn_id", "")
    actor = payload.get("actor", "")
    role = payload.get("role", "")
    verdict = payload.get("verdict", "")
    turn_text = _trunc(payload.get("turn_text", "") or "")
    end_reason = payload.get("end_reason", "")
    directive_text = _trunc(payload.get("directive_text", "") or "")
    directive_target = payload.get("directive_target", "")
    round_limit = payload.get("round_limit", round_)

    if event_type == "session_start":
        return {
            "text": f"kollab · session #{snum} started",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":rocket: Session Started — #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
            ],
        }

    if event_type == "turn_end":
        actor_label = actor.capitalize() + (f" ({role})" if role else "")
        return {
            "text": f"kollab · {turn_id} {verdict} (round {round_})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":speaking_head_in_silhouette: {turn_id} — {actor_label} · Round {round_}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Verdict:* `{verdict}`"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Response:*\n{turn_text}"}},
            ],
        }

    if event_type == "disagreement":
        actor_label = actor.capitalize() + (f" ({role})" if role else "")
        return {
            "text": f"kollab · disagreement on {turn_id} (round {round_})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":x: Disagreement — {turn_id} · Round {round_}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Actor:* {actor_label}"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                    {"type": "mrkdwn", "text": f"*Verdict:* `{verdict}`"},
                ]},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Critique:*\n{turn_text}"}},
            ],
        }

    if event_type == "convergence":
        return {
            "text": f"kollab · convergence reached (session #{snum})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":white_check_mark: Convergence — Session #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Rounds:* {round_}"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
            ],
        }

    if event_type == "round_limit":
        return {
            "text": f"kollab · round limit reached (session #{snum})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":warning: Round Limit — Session #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Rounds:* {round_} / {round_limit}"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
            ],
        }

    if event_type == "halt":
        return {
            "text": f"kollab · session #{snum} halted (round {round_})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":pause_button: Session Halted — #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Round:* {round_}"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
            ],
        }

    if event_type == "directive":
        target_label = directive_target.capitalize() if directive_target else "Unknown"
        return {
            "text": f"kollab · directive sent to {target_label} (session #{snum})",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":speech_balloon: Directive — Session #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Target:* {target_label}"},
                ]},
                {"type": "section", "text": {"type": "mrkdwn", "text": f"*Directive:*\n{directive_text}"}},
            ],
        }

    if event_type == "session_end":
        return {
            "text": f"kollab · session #{snum} ended — {end_reason}",
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f":checkered_flag: Session Ended — #{snum}"}},
                {"type": "section", "fields": [
                    {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                    {"type": "mrkdwn", "text": f"*Reason:* {end_reason}"},
                    {"type": "mrkdwn", "text": f"*Rounds:* {round_}"},
                    {"type": "mrkdwn", "text": f"*Goal:* {goal}"},
                ]},
            ],
        }

    return {
        "text": f"kollab · {event_type} (session #{snum})",
        "blocks": [
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Session:* #{snum} `{sid}`"},
                {"type": "mrkdwn", "text": f"*Event:* {event_type}"},
            ]},
        ],
    }
