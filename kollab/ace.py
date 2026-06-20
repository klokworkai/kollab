from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .agents.base import AgentChunk
from .agents.claude_agent import ClaudeAgent
from .agents.codex_agent import CodexAgent
from .attachments import (
    AttachmentMeta,
    build_text_attachment_block,
    collect_image_paths,
)
from .config import Config
from .prompts import (
    build_first_turn_prompt, build_turn_prompt, compose_system_prompt,
    system_critic, system_producer,
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
    max_tokens_per_session: int | None = None
    claude_model: str | None = None
    codex_model: str | None = None
    attachments: list[AttachmentMeta] = field(default_factory=list)
    claude_role: str = "producer"  # "producer" | "critic"


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
    anomaly: str | None = None
    interrupted: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None


class Session:
    def __init__(self, cfg: Config, broadcast: BroadcastFn,
                 overrides: SessionOverrides | None = None,
                 session_number: int = 0,
                 session_id: str | None = None) -> None:
        ov = overrides or SessionOverrides()
        self.id: str = session_id or _make_session_id()
        self.session_number: int = session_number
        self.goal: str = ""
        self.round: int = 0
        self.turns: list[Turn] = []
        self.state: SessionState = "idle"
        self._cfg = cfg
        self._broadcast = broadcast
        self._round_limit: int = ov.round_limit if ov.round_limit is not None else cfg.round_limit
        self._max_tokens_per_session: int | None = (
            ov.max_tokens_per_session if ov.max_tokens_per_session is not None else cfg.max_tokens_per_session
        )
        self._session_tokens: int = 0
        self.claude_role: str = ov.claude_role if ov.claude_role in ("producer", "critic") else "producer"
        codex_role: str = "critic" if self.claude_role == "producer" else "producer"
        if self.claude_role == "producer":
            self._claude_system: str = compose_system_prompt(
                system_producer("Claude", "Codex"), cfg.producer_user_prompt, cfg.producer_system_prompt_disabled,
                cfg.user_profile)
            self._codex_system: str = compose_system_prompt(
                system_critic("Codex", "Claude"), cfg.critic_user_prompt, cfg.critic_system_prompt_disabled,
                cfg.user_profile)
        else:
            self._claude_system = compose_system_prompt(
                system_critic("Claude", "Codex"), cfg.critic_user_prompt, cfg.critic_system_prompt_disabled,
                cfg.user_profile)
            self._codex_system = compose_system_prompt(
                system_producer("Codex", "Claude"), cfg.producer_user_prompt, cfg.producer_system_prompt_disabled,
                cfg.user_profile)
        self.producer_prompt_disabled: bool = cfg.producer_system_prompt_disabled
        self.critic_prompt_disabled: bool = cfg.critic_system_prompt_disabled
        self.producer_user_prompt: str = cfg.producer_user_prompt
        self.critic_user_prompt: str = cfg.critic_user_prompt
        self._claude = ClaudeAgent(
            role=self.claude_role,
            binary=cfg.claude_binary,
            model=ov.claude_model or cfg.claude_model,
            workdir=Path(cfg.claude_workdir).expanduser().__str__(),
            mcp_filesystem_enabled=cfg.mcp_filesystem_enabled,
            mcp_filesystem_paths=[Path(p).expanduser().__str__() for p in cfg.mcp_filesystem_paths],
        )
        self._codex = CodexAgent(
            role=codex_role,
            binary=cfg.codex_binary,
            model=ov.codex_model or cfg.codex_model,
            workdir=Path(cfg.codex_workdir).expanduser().__str__(),
            mcp_filesystem_enabled=cfg.mcp_filesystem_enabled,
            mcp_filesystem_paths=[Path(p).expanduser().__str__() for p in cfg.mcp_filesystem_paths],
        )
        self.claude_model: str = ov.claude_model or cfg.claude_model
        self.codex_model: str = ov.codex_model or cfg.codex_model
        self._transcript: TranscriptLog | None = None
        self._claude_turn_count: int = 0
        self._codex_turn_count: int = 0
        # Completed (non-interrupted) turn counts — drive round numbering.
        self._claude_completed: int = 0
        self._codex_completed: int = 0
        # Per-actor directive queues. Each entry is a string directive.
        # Keyed by 'claude' or 'codex'. Directives sent to 'both' are written
        # into both queues. Multiple directives accumulate instead of overwriting.
        self._pending_directives: dict[str, list[str]] = {"claude": [], "codex": []}
        self._attachments: list[AttachmentMeta] = list(ov.attachments)
        # Track whether each actor has received attachments on their first turn.
        # An interrupted turn does NOT count — the turn count stays at 1 so
        # delivery is retried on the re-run.
        self._attachments_delivered: dict[str, bool] = {"claude": False, "codex": False}
        self._halt_requested: bool = False
        self._done_reason: str = ""
        self._halt_timeout_secs: int = cfg.halt_timeout_secs
        self._halt_timer_task: asyncio.Task | None = None
        # Mid-turn halt tracking. After a mid-stream halt, _interrupted_agent
        # is the actor that was running. resume() reads this to know which
        # agent should run next (the same one that was interrupted) and sets
        # _resume_after_halt so the next prompt build prepends a notice telling
        # the agent to disregard its previous in-flight response.
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
                       "claude_model": self.claude_model,
                       "codex_model": self.codex_model,
                       "round_limit": self._round_limit,
                       "max_tokens_per_session": self._max_tokens_per_session,
                       "claude_role": self.claude_role,
                       "started_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                       "attachments": [a.to_dict() for a in self._attachments],
                       "producer_prompt_disabled": self.producer_prompt_disabled,
                       "critic_prompt_disabled": self.critic_prompt_disabled,
                       "producer_user_prompt": self.producer_user_prompt,
                       "critic_user_prompt": self.critic_user_prompt,
                   }})
        self._broadcast({"type": "state", "state": "fanning_out", "round": 0,
                         "session_number": self.session_number,
                         "session_id": self.id,
                         "claude_model": self.claude_model,
                         "codex_model": self.codex_model,
                         "claude_role": self.claude_role,
                         "round_limit": self._round_limit,
                         "max_tokens_per_session": self._max_tokens_per_session,
                         "producer_prompt_disabled": self.producer_prompt_disabled,
                         "critic_prompt_disabled": self.critic_prompt_disabled,
                         "producer_user_prompt": self.producer_user_prompt,
                         "critic_user_prompt": self.critic_user_prompt})
        self.state = "fanning_out"
        await asyncio.gather(
            self._claude.start(self._claude_system, goal),
            self._codex.start(self._codex_system, goal),
        )
        self.state = "claude_turn"
        self._broadcast({"type": "state", "state": "claude_turn", "round": 1})
        await self._emit("session_start", {"round": 0})

    async def run_turn(self) -> None:
        if self.state not in ("claude_turn", "codex_turn"):
            return

        is_claude = self.state == "claude_turn"
        agent = self._claude if is_claude else self._codex
        actor = "claude" if is_claude else "codex"
        role = agent.role
        peer_name = "Codex" if is_claude else "Claude"

        if is_claude:
            self._claude_turn_count += 1
            turn_id = f"C-{self._claude_turn_count}"
        else:
            self._codex_turn_count += 1
            turn_id = f"X-{self._codex_turn_count}"

        # Round = ceil((completed_claude + completed_codex + 1) / 2). The
        # +1 accounts for *this* turn-in-progress; interrupted turns never
        # increment the completed counters so they don't inflate the round.
        self.round = (self._claude_completed + self._codex_completed + 1 + 1) // 2

        turn = Turn(id=turn_id, actor=actor, role=role, round=self.round)
        self.turns.append(turn)
        log.info("turn_start %s actor=%s round=%d", turn_id, actor, self.round)
        self._log({"kind": "turn_start", "turn_id": turn_id, "actor": actor,
                   "role": role, "round": self.round, "payload": {}})
        model = self.claude_model if is_claude else self.codex_model
        self._broadcast({"type": "turn_start", "turn_id": turn_id,
                         "actor": actor, "role": role, "round": self.round,
                         "model": model})

        # ------ build prompt ------
        # Consume all pending directives for this actor and concatenate them.
        queue = self._pending_directives[actor]
        user_injection = "\n".join(queue) if queue else ""
        self._pending_directives[actor] = []

        resume_after_halt = self._resume_after_halt
        # Whether or not we use the resume prefix on this turn, we consume
        # the flag here — only the first turn after a halt gets the notice.
        self._resume_after_halt = False

        # First-real-turn detection: no completed peer turn exists yet. This
        # covers two cases — the very first turn of the session, and the
        # case where C-1 was interrupted before X-1 ever ran.
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

        # ------ attachment delivery (first turn per actor only) ------
        delivery_images: list = []
        if self._attachments and not self._attachments_delivered.get(actor, False):
            text_block = build_text_attachment_block(self._attachments)
            if text_block:
                prompt = text_block + "\n\n" + prompt
            delivery_images = collect_image_paths(self._attachments)

        # ------ stream the response ------
        self._halt_requested = False
        interrupted_mid_stream = False
        interrupt_signaled = False
        turn_tokens_in = 0
        turn_tokens_out = 0
        turn_thread_id = ""
        async for chunk in agent.send(prompt, images=delivery_images or None):
            # On halt: signal the agent to cancel (best effort) and stop
            # accumulating chunks into the turn. We DO continue iterating so
            # the underlying SDK / subprocess pipe drains naturally and is
            # ready for the next turn.
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
                continue  # drain remaining chunks but ignore them

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
                if actor == "claude":
                    turn_thread_id = meta.get("session_id") or self._claude._session_id or ""
                else:
                    turn_thread_id = self._codex._session_id or ""
                self._broadcast({"type": "turn_chunk", "turn_id": turn_id,
                                 "kind": "done", "content": ""})

        self._session_tokens += turn_tokens_in + turn_tokens_out

        # capture thread IDs after stream ends (agent._session_id is set by done chunk)
        if not turn_thread_id:
            if actor == "claude":
                turn_thread_id = self._claude._session_id or ""
            else:
                turn_thread_id = self._codex._session_id or ""

        turn.ended_at = datetime.now(timezone.utc)

        # Strip <tldr> from turn text before it enters conversation history or logs.
        turn.text, turn.summary = _parse_tldr(turn.text)

        # ------ interrupted path ------
        if self.state == "halted" and interrupted_mid_stream:
            turn.interrupted = True
            log.info("turn_interrupted %s actor=%s partial_len=%d", turn_id, actor, len(turn.text))
            # Keep the turn in self.turns as a permanent observable artifact.
            # Do NOT pop, do NOT decrement counters — turn IDs must remain
            # stable. Completed counters are NOT incremented (per spec, this
            # turn never happened from the dialogue's perspective).
            self._log({"kind": "turn_interrupted", "turn_id": turn_id, "actor": actor,
                       "role": role, "round": self.round,
                       "payload": {"text": turn.text, "reasoning": turn.reasoning,
                                   "thread_id": turn_thread_id}})
            self._interrupted_agent = actor
            # Inform UI: turn_cancel decorates the partial card; state goes halted.
            self._broadcast({"type": "turn_cancel", "turn_id": turn_id})
            self._broadcast({"type": "state", "state": "halted",
                             "round": self.round})
            await self._emit("halt", {"round": self.round})
            return

        # ------ normal completion ------
        # Mark attachments delivered for this actor (only on non-interrupted turns).
        if self._attachments and not self._attachments_delivered.get(actor, False):
            self._attachments_delivered[actor] = True

        turn.verdict = _parse_verdict(turn.text)
        duration_ms = int(
            (turn.ended_at - turn.started_at).total_seconds() * 1000
        )

        turn.anomaly = _detect_anomaly(turn.text, turn.verdict, is_first_turn=last_peer_turn is None)
        if turn.anomaly:
            log.warning("turn_anomaly %s actor=%s reason=%r", turn_id, actor, turn.anomaly)

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
                                "summary": turn.summary, "thread_id": turn_thread_id,
                                "anomaly": turn.anomaly}})
        self._broadcast({"type": "turn_end", "turn_id": turn_id,
                         "actor": actor,
                         "verdict": turn.verdict, "duration_ms": duration_ms,
                         "text": turn.text, "summary": turn.summary,
                         "anomaly": turn.anomaly,
                         "session_id": self.id})

        if self.state == "halted":
            # Clean halt that arrived between chunks but after the stream
            # ended naturally — treat as not-interrupted.
            self._broadcast({"type": "state", "state": "halted",
                             "round": self.round})
            await self._emit("halt", {"round": self.round})
            return

        # convergence tracking
        # Codex is the critic — a Codex AGREE means the debate is over,
        # regardless of what Claude said. No need for Claude to acknowledge.
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

        self._broadcast({"type": "state", "state": self.state,
                         "round": self.round})
        if self.state == "done":
            self._log({"kind": "session_end", "actor": "system", "role": "system",
                       "round": self.round, "payload": {"reason": self._done_reason}})
            self._broadcast({"type": "session_done", "reason": self._done_reason,
                             "session_id": self.id, "session_number": self.session_number,
                             "round_limit": self._round_limit})

        # Webhook emission — after all JSONL writes and WebSocket broadcasts.
        _turn_fields = {
            "round": self.round,
            "turn_id": turn_id,
            "actor": actor,
            "role": role,
            "verdict": turn.verdict,
            "turn_text": turn.text,
        }
        await self._emit("turn_end", _turn_fields)
        if turn.verdict == "DISAGREE":
            await self._emit("disagreement", _turn_fields)
        if self._done_reason == "convergence":
            await self._emit("convergence", {**_turn_fields, "end_reason": "convergence"})
        if self.state == "done":
            if self._done_reason == "round_limit":
                await self._emit("round_limit", {
                    "round": self.round,
                    "round_limit": self._round_limit,
                    "end_reason": "round_limit",
                })
            await self._emit("session_end", {
                "round": self.round,
                "end_reason": self._done_reason,
            })

    async def handle_user_input(self, text: str, target: str = "both") -> None:
        self._log({"kind": "user_input", "actor": "user", "role": "user",
                   "round": self.round, "payload": {"text": text, "target": target}})
        # Accumulate into per-actor queues. 'both' fans out to each queue.
        if target in ("claude", "both"):
            self._pending_directives["claude"].append(text)
        if target in ("codex", "both"):
            self._pending_directives["codex"].append(text)
        await self._emit("directive", {"directive_text": text, "directive_target": target})

    def stop(self) -> None:
        log.info("session_stop id=%s state=%s", self.id, self.state)
        self.state = "halted"
        self._halt_requested = True
        # cancel any existing timer first
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
        # schedule auto-expiry if timeout is configured
        if self._halt_timeout_secs > 0:
            self._halt_timer_task = asyncio.create_task(
                self._halt_timeout_task(self._halt_timeout_secs)
            )

    async def _halt_timeout_task(self, seconds: int) -> None:
        """Auto-expire the session if still halted after `seconds`."""
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

    async def end_now(self) -> None:
        """Explicitly terminate a halted session without waiting for auto-expiry."""
        if self.state != "halted":
            return
        log.info("session_end_now id=%s", self.id)
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
            self._halt_timer_task = None
        self._done_reason = "halted"
        self.state = "done"
        self._log({"kind": "session_end", "actor": "system", "role": "system",
                   "round": self.round,
                   "payload": {"reason": "halted", "detail": "Session ended by user."}})
        self._broadcast({"type": "session_done", "reason": "halted",
                         "session_id": self.id, "session_number": self.session_number,
                         "round_limit": self._round_limit})
        await self._emit("session_end", {
            "round": self.round,
            "end_reason": "halted",
        })
        await self.close()

    async def resume(self) -> None:
        if self.state != "halted":
            return
        log.info("session_resume id=%s interrupted_agent=%s", self.id, self._interrupted_agent)
        # cancel halt timer
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
            self._halt_timer_task = None

        if self._interrupted_agent is not None:
            # Mid-stream halt — the same agent that was interrupted runs again
            # with a fresh prompt built from clean history (interrupted turns
            # are filtered out by _last_turn_for). The next prompt gets a
            # "disregard previous in-flight" prefix so the agent doesn't
            # try to continue its abandoned thought.
            self.state = "claude_turn" if self._interrupted_agent == "claude" else "codex_turn"
            self._interrupted_agent = None
            self._resume_after_halt = True
        else:
            # Clean halt between turns — peer goes next.
            if self.turns and self.turns[-1].actor == "claude":
                self.state = "codex_turn"
            else:
                self.state = "claude_turn"

        self._broadcast({"type": "state", "state": self.state,
                         "round": self.round})

    async def close(self) -> None:
        if self._halt_timer_task and not self._halt_timer_task.done():
            self._halt_timer_task.cancel()
        await asyncio.gather(
            self._claude.stop(),
            self._codex.stop(),
            return_exceptions=True,
        )
        if self._transcript:
            self._transcript.close()

    # ------------------------------------------------------------------ helpers

    async def _emit(self, event_type: str, extra: dict | None = None) -> None:
        """Build common fields, merge extra, fire webhook. Swallows all errors."""
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
        """Return the most recent COMPLETED turn for `actor`. Interrupted
        turns are skipped — per spec, an interrupted turn is invisible to
        downstream prompt building."""
        for t in reversed(self.turns):
            if t.actor == actor and not t.interrupted:
                return t
        return None


# ------------------------------------------------------------------ helpers

def _make_session_id() -> str:
    import uuid
    return f"sess_{uuid.uuid4().hex[:8]}"


def _detect_anomaly(text: str, verdict: Verdict | None, is_first_turn: bool) -> str | None:
    """Flag a completed turn whose output is empty and/or missing a verdict
    trailer — a sign the agent's response was degenerate (e.g. starved by an
    unrealistic token request), not a normal outcome. C-1 never carries a
    verdict by design, so a missing verdict there is not anomalous."""
    reasons: list[str] = []
    if not text.strip():
        reasons.append("empty response text")
    if verdict is None and not is_first_turn:
        reasons.append("no verdict trailer")
    return ", ".join(reasons) if reasons else None


def _parse_verdict(text: str) -> Verdict | None:
    m = _VERDICT_RE.search(text)
    if m:
        return m.group(1).upper()  # type: ignore[return-value]
    return None


def _parse_tldr(text: str) -> tuple[str, str]:
    """Extract <tldr> summary and return (cleaned_text, summary).
    The <tldr> block is stripped from the text so it never reaches the next agent."""
    m = _TLDR_RE.search(text)
    if not m:
        return text, ""
    summary = m.group(1).strip()
    cleaned = _TLDR_RE.sub("", text).rstrip()
    return cleaned, summary
