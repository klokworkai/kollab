from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .agents import make_agent
from .agents.base import AgentChunk
from .config import Config, ProviderConfig
from .prompts import (
    SYSTEM_CRITIC, SYSTEM_PRODUCER,
    build_first_turn_prompt, build_turn_prompt,
)
from .transcript import TranscriptLog
from .webhooks import emit

_VERDICT_RE = re.compile(r"<verdict>\s*(AGREE|DISAGREE|REVISED)\s*</verdict>", re.I)
_TLDR_RE    = re.compile(r"\s*<tldr>\s*(.*?)\s*</tldr>", re.I | re.DOTALL)

log = logging.getLogger("kollab.ace")

Verdict = Literal["AGREE", "DISAGREE", "REVISED"]
SessionState = Literal[
    "idle", "fanning_out", "claude_turn", "codex_turn",
    "awaiting_user", "done", "halted",
]

# Broadcast callback: receives a JSON-serialisable dict per event.
BroadcastFn = Callable[[dict], None]


@dataclass
class SessionOverrides:
    round_limit: int | None = None
    max_tokens_per_turn: int | None = None
    max_tokens_per_session: int | None = None
    producer_provider_id: str | None = None
    producer_model: str | None = None
    critic_provider_id: str | None = None
    critic_model: str | None = None


@dataclass
class Turn:
    id: str
    actor: str
    role: str
    round: int
    text: str = ""
    reasoning: str = ""
    summary: str = ""
    verdict: Verdict | None = None
    interrupted: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None


class Session:
    def __init__(self, cfg: Config, broadcast: BroadcastFn,
                 overrides: SessionOverrides | None = None,
                 session_number: int = 0) -> None:
        ov = overrides or SessionOverrides()
        self.id: str = _make_session_id()
        self.session_number: int = session_number
        self.goal: str = ""
        self.round: int = 0
        self.turns: list[Turn] = []
        self.state: SessionState = "idle"
        self._cfg = cfg
        self._broadcast = broadcast
        self._round_limit: int = ov.round_limit if ov.round_limit is not None else cfg.round_limit
        self._max_tokens_per_turn: int | None = ov.max_tokens_per_turn
        self._max_tokens_per_session: int | None = ov.max_tokens_per_session
        self._session_tokens: int = 0

        producer_prov = _resolve_provider(cfg, ov.producer_provider_id, 0)
        critic_prov   = _resolve_provider(cfg, ov.critic_provider_id, 1)
        self.producer_model: str = _resolve_model(producer_prov, ov.producer_model)
        self.critic_model: str   = _resolve_model(critic_prov, ov.critic_model)
        self.producer_provider_id: str = producer_prov.id
        self.critic_provider_id: str   = critic_prov.id
        self.producer_name: str = producer_prov.name
        self.critic_name: str   = critic_prov.name

        self._producer = make_agent(producer_prov, "producer", self.producer_model, cfg)
        self._critic   = make_agent(critic_prov,   "critic",   self.critic_model,   cfg)

        self._transcript: TranscriptLog | None = None
        self._claude_turn_count: int = 0
        self._codex_turn_count: int = 0
        self._claude_completed: int = 0
        self._codex_completed: int = 0
        # Directive queues keyed by actor ("claude" / "codex") — API matches existing frontend.
        self._pending_directives: dict[str, list[str]] = {"claude": [], "codex": []}
        self._halt_requested: bool = False
        self._done_reason: str = ""
        self._halt_timeout_secs: int = cfg.halt_timeout_secs
        self._halt_timer_task: asyncio.Task | None = None
        self._interrupted_agent: str | None = None
        self._resume_after_halt: bool = False

    # ------------------------------------------------------------------ lifecycle

    async def start(self, goal: str) -> None:
        self.goal = goal
        sessions_dir = Path(self._cfg.sessions_dir).expanduser()
        self._transcript = TranscriptLog(self.id, sessions_dir)
        log.info("session_start id=%s number=%s goal=%r", self.id, self.session_number, goal[:80])
        self._log({"kind": "session_start", "actor": "system", "role": "system",
                   "round": 0, "payload": {
                       "goal": goal,
                       "session_number": self.session_number,
                       "producer_provider_id": self.producer_provider_id,
                       "critic_provider_id": self.critic_provider_id,
                       "producer_name": self.producer_name,
                       "critic_name": self.critic_name,
                       "producer_model": self.producer_model,
                       "critic_model": self.critic_model,
                       "round_limit": self._round_limit,
                       "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   }})
        self._broadcast({"type": "state", "state": "fanning_out", "round": 0,
                         "session_number": self.session_number,
                         "session_id": self.id,
                         "producer_provider_id": self.producer_provider_id,
                         "critic_provider_id": self.critic_provider_id,
                         "producer_name": self.producer_name,
                         "critic_name": self.critic_name,
                         "producer_model": self.producer_model,
                         "critic_model": self.critic_model,
                         "round_limit": self._round_limit})
        self.state = "fanning_out"
        await asyncio.gather(
            self._producer.start(SYSTEM_PRODUCER, goal),
            self._critic.start(SYSTEM_CRITIC, goal),
        )
        self.state = "claude_turn"
        self._broadcast({"type": "state", "state": "claude_turn", "round": 1})
        await self._emit("session_start", {"round": 0})

    async def run_turn(self) -> None:
        if self.state not in ("claude_turn", "codex_turn"):
            return

        is_claude = self.state == "claude_turn"
        agent = self._producer if is_claude else self._critic
        actor = "claude" if is_claude else "codex"
        role  = "producer" if is_claude else "critic"
        peer_name = self.critic_name if is_claude else self.producer_name

        if is_claude:
            self._claude_turn_count += 1
            turn_id = f"C-{self._claude_turn_count}"
        else:
            self._codex_turn_count += 1
            turn_id = f"X-{self._codex_turn_count}"

        self.round = (self._claude_completed + self._codex_completed + 1 + 1) // 2

        turn = Turn(id=turn_id, actor=actor, role=role, round=self.round)
        self.turns.append(turn)
        log.info("turn_start %s actor=%s round=%d", turn_id, actor, self.round)
        self._log({"kind": "turn_start", "turn_id": turn_id, "actor": actor,
                   "role": role, "round": self.round, "payload": {}})
        model = self.producer_model if is_claude else self.critic_model
        self._broadcast({"type": "turn_start", "turn_id": turn_id,
                         "actor": actor, "role": role, "round": self.round,
                         "model": model})

        queue = self._pending_directives[actor]
        user_injection = "\n".join(queue) if queue else ""
        self._pending_directives[actor] = []

        resume_after_halt = self._resume_after_halt
        self._resume_after_halt = False

        last_peer_turn = self._last_turn_for("codex" if is_claude else "claude")
        if last_peer_turn is None:
            prompt = build_first_turn_prompt(
                self.goal,
                user_injection=user_injection,
                resume_after_halt=resume_after_halt,
            )
        else:
            prompt = build_turn_prompt(
                self.round,
                peer_name,
                last_peer_turn.text,
                user_injection=user_injection,
                resume_after_halt=resume_after_halt,
            )

        if self._max_tokens_per_turn:
            prompt += f"\n[Keep this response under {self._max_tokens_per_turn} tokens.]"

        self._halt_requested = False
        interrupted_mid_stream = False
        interrupt_signaled = False
        turn_tokens_in = 0
        turn_tokens_out = 0
        turn_thread_id = ""
        async for chunk in agent.send(prompt):
            if self._halt_requested:
                interrupted_mid_stream = True
                if not interrupt_signaled:
                    interrupt_signaled = True
                    log.info("turn_interrupt_signal %s actor=%s", turn_id, actor)
                    try:
                        await agent.interrupt()
                    except Exception as exc:
                        log.warning("interrupt() raised: %s", exc)
                log.debug("drain chunk kind=%s turn=%s", chunk.kind, turn_id)
                continue

            if chunk.kind == "text":
                turn.text += chunk.content
                self._broadcast({"type": "turn_chunk", "turn_id": turn_id,
                                 "kind": "text", "content": chunk.content})
            elif chunk.kind == "reasoning":
                turn.reasoning += chunk.content
                self._broadcast({"type": "turn_chunk", "turn_id": turn_id,
                                 "kind": "reasoning", "content": chunk.content})
            elif chunk.kind == "done":
                meta = chunk.metadata or {}
                turn_tokens_in = meta.get("tokens_in") or 0
                turn_tokens_out = meta.get("tokens_out") or 0
                turn_thread_id = meta.get("session_id") or agent.thread_id
                self._broadcast({"type": "turn_chunk", "turn_id": turn_id,
                                 "kind": "done", "content": ""})

        self._session_tokens += turn_tokens_in + turn_tokens_out

        if not turn_thread_id:
            turn_thread_id = agent.thread_id

        turn.ended_at = datetime.now(timezone.utc)
        turn.text, turn.summary = _parse_tldr(turn.text)

        if self.state == "halted" and interrupted_mid_stream:
            turn.interrupted = True
            log.info("turn_interrupted %s actor=%s partial_len=%d", turn_id, actor, len(turn.text))
            self._log({"kind": "turn_interrupted", "turn_id": turn_id, "actor": actor,
                       "role": role, "round": self.round,
                       "payload": {"text": turn.text, "reasoning": turn.reasoning,
                                   "thread_id": turn_thread_id}})
            self._interrupted_agent = actor
            self._broadcast({"type": "turn_cancel", "turn_id": turn_id})
            self._broadcast({"type": "state", "state": "halted", "round": self.round})
            await self._emit("halt", {"round": self.round})
            return

        turn.verdict = _parse_verdict(turn.text)
        duration_ms = int((turn.ended_at - turn.started_at).total_seconds() * 1000)
        log.info("turn_end %s actor=%s verdict=%s duration_ms=%d tokens_in=%d tokens_out=%d",
                 turn_id, actor, turn.verdict, duration_ms, turn_tokens_in, turn_tokens_out)
        if is_claude:
            self._claude_completed += 1
        else:
            self._codex_completed += 1

        self._log({"kind": "turn_end", "turn_id": turn_id, "actor": actor,
                   "role": role, "round": self.round,
                   "payload": {"text": turn.text, "reasoning": turn.reasoning,
                                "verdict": turn.verdict, "duration_ms": duration_ms,
                                "summary": turn.summary, "thread_id": turn_thread_id}})
        self._broadcast({"type": "turn_end", "turn_id": turn_id,
                         "verdict": turn.verdict, "duration_ms": duration_ms,
                         "text": turn.text, "summary": turn.summary,
                         "session_id": self.id})

        if self.state == "halted":
            self._broadcast({"type": "state", "state": "halted", "round": self.round})
            await self._emit("halt", {"round": self.round})
            return

        if not is_claude and turn.verdict == "AGREE":
            self._done_reason = "convergence"
            self.state = "done"
        elif self._max_tokens_per_session and self._session_tokens >= self._max_tokens_per_session:
            self._done_reason = "token_limit"
            self.state = "done"
        elif self.round >= self._round_limit and not is_claude:
            self._done_reason = "round_limit"
            self.state = "done"
        else:
            self.state = "codex_turn" if is_claude else "claude_turn"

        self._broadcast({"type": "state", "state": self.state, "round": self.round})
        if self.state == "done":
            self._log({"kind": "session_end", "actor": "system", "role": "system",
                       "round": self.round, "payload": {"reason": self._done_reason}})
            self._broadcast({"type": "session_done", "reason": self._done_reason,
                             "session_id": self.id, "session_number": self.session_number,
                             "round_limit": self._round_limit})

        _turn_fields = {
            "round": self.round, "turn_id": turn_id, "actor": actor,
            "role": role, "verdict": turn.verdict, "turn_text": turn.text,
        }
        await self._emit("turn_end", _turn_fields)
        if turn.verdict == "DISAGREE":
            await self._emit("disagreement", _turn_fields)
        if self._done_reason == "convergence":
            await self._emit("convergence", {**_turn_fields, "end_reason": "convergence"})
        if self.state == "done":
            if self._done_reason == "round_limit":
                await self._emit("round_limit", {
                    "round": self.round, "round_limit": self._round_limit,
                    "end_reason": "round_limit",
                })
            await self._emit("session_end", {"round": self.round, "end_reason": self._done_reason})

    async def handle_user_input(self, text: str, target: str = "both") -> None:
        self._log({"kind": "user_input", "actor": "user", "role": "user",
                   "round": self.round, "payload": {"text": text, "target": target}})
        if target in ("claude", "both"):
            self._pending_directives["claude"].append(text)
        if target in ("codex", "both"):
            self._pending_directives["codex"].append(text)
        await self._emit("directive", {"directive_text": text, "directive_target": target})

    def stop(self) -> None:
        log.info("session_stop id=%s state=%s", self.id, self.state)
        self.state = "halted"
        self._halt_requested = True
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
        if self._halt_timeout_secs > 0:
            self._halt_timer_task = asyncio.create_task(
                self._halt_timeout_task(self._halt_timeout_secs)
            )

    async def _halt_timeout_task(self, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        if self.state != "halted":
            return
        self._done_reason = "expired"
        self.state = "done"
        self._log({"kind": "session_end", "actor": "system", "role": "system",
                   "round": self.round,
                   "payload": {"reason": "expired",
                               "detail": f"Session auto-expired after {seconds}s halt"}})
        self._broadcast({"type": "session_done", "reason": "expired",
                         "session_id": self.id, "session_number": self.session_number,
                         "round_limit": self._round_limit})
        await self.close()

    async def resume(self) -> None:
        if self.state != "halted":
            return
        log.info("session_resume id=%s interrupted_agent=%s", self.id, self._interrupted_agent)
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
            self._halt_timer_task = None

        if self._interrupted_agent is not None:
            self.state = "claude_turn" if self._interrupted_agent == "claude" else "codex_turn"
            self._interrupted_agent = None
            self._resume_after_halt = True
        else:
            if self.turns and self.turns[-1].actor == "claude":
                self.state = "codex_turn"
            else:
                self.state = "claude_turn"

        self._broadcast({"type": "state", "state": self.state, "round": self.round})

    async def close(self) -> None:
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
        await asyncio.gather(
            self._producer.stop(),
            self._critic.stop(),
            return_exceptions=True,
        )
        if self._transcript:
            self._transcript.close()

    # ------------------------------------------------------------------ helpers

    async def _emit(self, event_type: str, extra: dict | None = None) -> None:
        payload: dict = {
            "session_id": self.id,
            "session_number": self.session_number,
            "goal": self.goal,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
        if extra:
            payload.update(extra)
        try:
            await emit(event_type, payload, self._cfg)
        except Exception as exc:
            log.error("webhook emit unexpected error event=%s error=%s", event_type, exc)

    def _log(self, event: dict) -> None:
        if self._transcript:
            event["session_id"] = self.id
            self._transcript.append(event)

    def _last_turn_for(self, actor: str) -> Turn | None:
        for t in reversed(self.turns):
            if t.actor == actor and not t.interrupted:
                return t
        return None


# ------------------------------------------------------------------ helpers

def _make_session_id() -> str:
    import uuid
    return f"sess_{uuid.uuid4().hex[:8]}"


def _resolve_provider(cfg: Config, provider_id: str | None, fallback_idx: int) -> ProviderConfig:
    enabled = [p for p in cfg.providers if p.enabled]
    if provider_id:
        match = next((p for p in enabled if p.id == provider_id), None)
        if match:
            return match
        match = next((p for p in cfg.providers if p.id == provider_id), None)
        if match:
            return match
    if enabled and fallback_idx < len(enabled):
        return enabled[fallback_idx]
    if cfg.providers:
        return cfg.providers[min(fallback_idx, len(cfg.providers) - 1)]
    raise ValueError("No providers configured")


def _resolve_model(provider: ProviderConfig, model_alias_or_id: str | None) -> str:
    if not model_alias_or_id:
        return provider.models[0].model_id if provider.models else ""
    for m in provider.models:
        if m.alias == model_alias_or_id:
            return m.model_id
    return model_alias_or_id


def _parse_verdict(text: str) -> Verdict | None:
    m = _VERDICT_RE.search(text)
    if m:
        return m.group(1).upper()  # type: ignore[return-value]
    return None


def _parse_tldr(text: str) -> tuple[str, str]:
    m = _TLDR_RE.search(text)
    if not m:
        return text, ""
    summary = m.group(1).strip()
    cleaned = _TLDR_RE.sub("", text).rstrip()
    return cleaned, summary
