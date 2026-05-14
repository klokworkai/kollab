from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .agents.base import AgentChunk
from .agents.claude_agent import ClaudeAgent
from .agents.codex_agent import CodexAgent
from .config import Config
from .prompts import (
    SYSTEM_CRITIC, SYSTEM_PRODUCER,
    build_first_turn_prompt, build_turn_prompt,
)
from .transcript import TranscriptLog

_VERDICT_RE = re.compile(r"<verdict>\s*(AGREE|DISAGREE|REVISED)\s*</verdict>", re.I)

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
    claude_model: str | None = None
    codex_model: str | None = None


@dataclass
class Turn:
    id: str
    actor: str
    role: str
    round: int
    text: str = ""
    reasoning: str = ""
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
        self.consecutive_agrees: int = 0  # kept for broadcast compat; convergence now driven by Codex AGREE alone
        self._cfg = cfg
        self._broadcast = broadcast
        self._round_limit: int = ov.round_limit if ov.round_limit is not None else cfg.round_limit
        self._max_tokens_per_turn: int | None = ov.max_tokens_per_turn
        self._max_tokens_per_session: int | None = ov.max_tokens_per_session
        self._session_tokens: int = 0
        self._claude = ClaudeAgent(
            role="producer",
            binary=cfg.claude_binary,
            model=ov.claude_model or cfg.claude_model,
            workdir=Path(cfg.claude_workdir).expanduser().__str__(),
            mcp_filesystem_enabled=cfg.mcp_filesystem_enabled,
            mcp_filesystem_paths=[Path(p).expanduser().__str__() for p in cfg.mcp_filesystem_paths],
        )
        self._codex = CodexAgent(
            role="critic",
            binary=cfg.codex_binary,
            model=ov.codex_model or cfg.codex_model,
            workdir=Path(cfg.codex_workdir).expanduser().__str__(),
            mcp_filesystem_enabled=cfg.mcp_filesystem_enabled,
            mcp_filesystem_paths=[Path(p).expanduser().__str__() for p in cfg.mcp_filesystem_paths],
        )
        self._transcript: TranscriptLog | None = None
        self._claude_turn_count: int = 0
        self._codex_turn_count: int = 0
        # Completed (non-interrupted) turn counts — drive round numbering.
        self._claude_completed: int = 0
        self._codex_completed: int = 0
        self._pending_user_input: str = ""
        self._pending_user_input_target: str = "both"  # 'claude' | 'codex' | 'both'
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
        self._log({"kind": "session_start", "actor": "system", "role": "system",
                   "round": 0, "payload": {"goal": goal, "session_number": self.session_number}})
        self._broadcast({"type": "state", "state": "fanning_out", "round": 0,
                         "consecutive_agrees": 0, "session_number": self.session_number,
                         "session_id": self.id})
        self.state = "fanning_out"
        await asyncio.gather(
            self._claude.start(SYSTEM_PRODUCER, goal),
            self._codex.start(SYSTEM_CRITIC, goal),
        )
        self.state = "claude_turn"
        self._broadcast({"type": "state", "state": "claude_turn", "round": 1,
                         "consecutive_agrees": 0})

    async def run_turn(self) -> None:
        if self.state not in ("claude_turn", "codex_turn"):
            return

        is_claude = self.state == "claude_turn"
        agent = self._claude if is_claude else self._codex
        actor = "claude" if is_claude else "codex"
        role = "producer" if is_claude else "critic"
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
        self._log({"kind": "turn_start", "turn_id": turn_id, "actor": actor,
                   "role": role, "round": self.round, "payload": {}})
        self._broadcast({"type": "turn_start", "turn_id": turn_id,
                         "actor": actor, "role": role, "round": self.round})

        # ------ build prompt ------
        # Determine and consume any pending user directive that targets this
        # actor. Same-as-before semantics: if target is 'both', the first
        # consuming agent flips it to the peer so both see it once.
        user_injection = self._pending_user_input
        if user_injection:
            target = self._pending_user_input_target
            if target not in (actor, "both"):
                user_injection = ""  # not for this agent — leave pending
            else:
                if target == "both":
                    peer_actor = "codex" if is_claude else "claude"
                    self._pending_user_input_target = peer_actor
                else:
                    self._pending_user_input = ""
                    self._pending_user_input_target = "both"

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

        if self._max_tokens_per_turn:
            prompt += f"\n[Keep this response under {self._max_tokens_per_turn} tokens.]"

        # ------ stream the response ------
        self._halt_requested = False
        interrupted_mid_stream = False
        interrupt_signaled = False
        turn_tokens_in = 0
        turn_tokens_out = 0
        turn_thread_id = ""
        async for chunk in agent.send(prompt):
            # On halt: signal the agent to cancel (best effort) and stop
            # accumulating chunks into the turn. We DO continue iterating so
            # the underlying SDK / subprocess pipe drains naturally and is
            # ready for the next turn.
            if self._halt_requested:
                interrupted_mid_stream = True
                if not interrupt_signaled:
                    interrupt_signaled = True
                    try:
                        await agent.interrupt()
                    except Exception:
                        pass
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

        # ------ interrupted path ------
        if self.state == "halted" and interrupted_mid_stream:
            turn.interrupted = True
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
                             "round": self.round,
                             "consecutive_agrees": self.consecutive_agrees})
            return

        # ------ normal completion ------
        turn.verdict = _parse_verdict(turn.text)
        duration_ms = int(
            (turn.ended_at - turn.started_at).total_seconds() * 1000
        )
        if is_claude:
            self._claude_completed += 1
        else:
            self._codex_completed += 1

        self._log({"kind": "turn_end", "turn_id": turn_id, "actor": actor,
                   "role": role, "round": self.round,
                   "payload": {"text": turn.text, "reasoning": turn.reasoning,
                                "verdict": turn.verdict, "duration_ms": duration_ms,
                                "thread_id": turn_thread_id}})
        self._broadcast({"type": "turn_end", "turn_id": turn_id,
                         "verdict": turn.verdict, "duration_ms": duration_ms,
                         "thread_id": turn_thread_id})

        if self.state == "halted":
            # Clean halt that arrived between chunks but after the stream
            # ended naturally — treat as not-interrupted.
            self._broadcast({"type": "state", "state": "halted",
                             "round": self.round, "consecutive_agrees": self.consecutive_agrees})
            return

        # convergence tracking
        # Codex is the critic — a Codex AGREE means the debate is over,
        # regardless of what Claude said. No need for Claude to acknowledge.
        if not is_claude and turn.verdict == "AGREE":
            self.consecutive_agrees += 1  # will be 1; kept for UI broadcast
            self._done_reason = "convergence"
            self.state = "done"
        elif self._max_tokens_per_session and self._session_tokens >= self._max_tokens_per_session:
            self._done_reason = "token_limit"
            self.state = "done"
        elif self.round >= self._round_limit and not is_claude:
            self._done_reason = "round_limit"
            self.state = "done"
        else:
            if turn.verdict == "AGREE":
                self.consecutive_agrees += 1
            else:
                self.consecutive_agrees = 0
            self.state = "codex_turn" if is_claude else "claude_turn"

        self._broadcast({"type": "state", "state": self.state,
                         "round": self.round, "consecutive_agrees": self.consecutive_agrees})
        if self.state == "done":
            self._log({"kind": "session_end", "actor": "system", "role": "system",
                       "round": self.round, "payload": {"reason": self._done_reason}})
            self._broadcast({"type": "session_done", "reason": self._done_reason,
                             "session_id": self.id, "session_number": self.session_number})

    async def handle_user_input(self, text: str, target: str = "both") -> None:
        self._log({"kind": "user_input", "actor": "user", "role": "user",
                   "round": self.round, "payload": {"text": text, "target": target}})
        self._pending_user_input = text
        self._pending_user_input_target = target

    def stop(self) -> None:
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
                         "session_id": self.id, "session_number": self.session_number})
        await self.close()

    async def resume(self) -> None:
        if self.state != "halted":
            return
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
                         "round": self.round, "consecutive_agrees": self.consecutive_agrees})

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


def _parse_verdict(text: str) -> Verdict | None:
    m = _VERDICT_RE.search(text)
    if m:
        return m.group(1).upper()  # type: ignore[return-value]
    return None
