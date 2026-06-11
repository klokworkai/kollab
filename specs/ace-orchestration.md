# ACE Orchestration Spec

**Component:** ACE — Adversarial Collab Engine  
**Module:** `ace.py`, `prompts.py`  
**Version:** v2  
**Status:** Reflects current implementation

---

## 1. Purpose

ACE is the orchestration control plane for a kollab session. It is a reconciliation loop: the desired state is convergence between two AI agents on a shared goal; the actual state is the current verdict and round count; ACE continuously drives toward the desired state by sequencing turns, enforcing role boundaries, and parsing structured signals from agent output.

ACE does not try to understand the content of what the agents produce. It reads one structured signal — the `<verdict>` trailer — and acts on it mechanically. The intelligence is in the agents. ACE runs the show.

This framing maps directly to known platform engineering patterns:
- **Kubernetes controller** — desired state (convergence) vs actual state (current verdict), reconcile loop
- **GitOps** — declarative goal submitted once, engine drives toward it without further input
- **Workflow engine** — explicit state machine, deterministic transitions, terminal states
- **Service mesh arbitration** — neutral coordination layer between two independent systems

---

## 2. Actors

### 2.1 Claude

- **Role:** Assigned per session — either producer or critic. Default is producer. Role is set via `claude_role` in `SessionOverrides` and is fixed for the session lifetime.
- **Transport:** Claude Agent SDK (`claude-agent-sdk`). In-process, streaming. `interrupt()` cancels in-flight turn without tearing down the session.
- **Session memory:** Persistent across all turns via `ClaudeSDKClient`. ACE passes only the peer's latest message — Claude builds on its own prior context internally.
- **Identity signal:** `session_id` from `ResultMessage` after each turn. Shown in UI as truncated badge.
- **MCP:** Filesystem MCP supported when `mcp_filesystem_enabled` is true.

### 2.2 Codex

- **Role:** Assigned per session — the inverse of Claude's role. If Claude is producer, Codex is critic; if Claude is critic, Codex is producer. Fixed for the session lifetime.
- **Transport:** `codex exec` CLI as subprocess. JSON stream on stdout. `interrupt()` calls `proc.terminate()` with 2s timeout before `proc.kill()`. Session continuity preserved — `_session_id` (thread ID) is never cleared.
- **Session memory:** Persistent across turns via `codex exec resume <thread_id>`. Thread ID captured from `thread.started` event on first turn.
- **MCP:** Not supported. `codex exec` CLI has no `--mcp-server` flag. MCP constructor params are accepted but no-op.

**Convergence authority belongs to the critic**, regardless of which agent holds that role. The critic's `AGREE` is the sole convergence signal. The producer's `AGREE` has no mechanical effect on session state.

### 2.3 User — Observer and Director

- **Role during turns:** Observer. Neither agent receives user messages during an active turn. The user watches the streaming dialogue.
- **Role while halted:** Director. Can send directives to one or both agents before resuming. Directives are queued and injected into the next turn prompt for the targeted actor.
- **Intervention model:** Stop → (optional directive) → Resume. Stop can fire at any point including mid-stream. Resume reactivates the same agent that was running (mid-stream halt) or the peer agent (clean halt).

### 2.4 ACE — Orchestrator

- **Role:** Neutral coordination layer. Owns session state, turn sequencing, prompt construction, verdict parsing, halt/resume lifecycle, event logging, and WebSocket broadcast.
- **Does not:** Interpret content, resolve disagreements, choose sides, or modify agent output.

---

## 3. Session State Machine

### 3.1 States

| State | Description |
|---|---|
| `idle` | No active session. Waiting for a goal submission. |
| `fanning_out` | Goal submitted. Both agents initialised in parallel. Neither has produced output yet. |
| `claude_turn` | Claude is the active agent. Turn is either streaming or about to start. |
| `codex_turn` | Codex is the active agent. Turn is either streaming or about to start. |
| `halted` | Session suspended. No agent is active. User may send directives or resume. Halt timer running if `halt_timeout_secs > 0`. |
| `done` | Session reached a terminal state. No further turns will run. |

### 3.2 Transition rules

```
idle
  → fanning_out       POST /api/session received; goal delivered to both agents in parallel

fanning_out
  → claude_turn       Both agents initialised; Claude goes first always

claude_turn
  → codex_turn        Claude turn completes normally; verdict is not AGREE (or C-1)
  → halted            stop() called (clean halt between turns, or mid-stream)
  → done              (not reachable from claude_turn directly — done is set after codex_turn)

codex_turn
  → claude_turn       Codex turn completes; verdict is DISAGREE or REVISED
  → halted            stop() called (clean halt or mid-stream)
  → done              Codex verdict is AGREE, OR round == round_limit, OR session_tokens >= max_tokens_per_session

halted
  → claude_turn       resume() called; prior active agent was Claude (mid-stream) or Codex (clean)
  → codex_turn        resume() called; prior active agent was Codex (mid-stream) or Claude (clean)
  → done              halt_timeout_secs elapsed without resume; end_reason = "expired"

done
  → (terminal)        No transitions out of done.
```

### 3.3 Who goes next on resume

Resume logic is determined by `_interrupted_agent` and the last completed turn:

| Halt type | `_interrupted_agent` | Next state on resume |
|---|---|---|
| Mid-stream halt (Claude was streaming) | `"claude"` | `claude_turn` |
| Mid-stream halt (Codex was streaming) | `"codex"` | `codex_turn` |
| Clean halt (between turns, Claude just finished) | `None` | `codex_turn` |
| Clean halt (between turns, Codex just finished) | `None` | `claude_turn` |
| Clean halt before any turn completed | `None` | `claude_turn` |

---

## 4. Turn Lifecycle

### 4.1 Turn ID assignment

Turn IDs are stable for the session lifetime. They are never reassigned, never decremented, and never reused.

- Claude turns: `C-{n}` where `n = _claude_turn_count` incremented at the start of each Claude turn
- Codex turns: `X-{n}` where `n = _codex_turn_count` incremented at the start of each Codex turn
- An interrupted C-3 stays C-3. The next Claude turn is C-4.

Claude always goes first regardless of role assignment — so the first turn is always `C-1`. However, the *role* on that turn depends on session configuration: `C-1` is a `PROPOSAL` if Claude is the producer, or an adversarial opening critique if Claude is the critic.

### 4.2 Round numbering

Round is computed at the start of each turn:

```
round = ceil((_claude_completed + _codex_completed + 1 + 1) / 2)
```

`_claude_completed` and `_codex_completed` count only **completed** (non-interrupted) turns. Interrupted turns do not increment these counters.

### 4.3 Prompt construction

ACE constructs the prompt for each turn via `prompts.py`. The prompt is never replayed from JSONL — it is always freshly built from the current session state.

**First turn (C-1):** `build_first_turn_prompt(goal, user_injection, resume_after_halt)`

```
[Round 1] <goal>
[User directive — address this first]: <directive>   ← only if queued

Produce your initial proposal. Do NOT include a <verdict> trailer on this first turn.
```

**Subsequent turns:** `build_turn_prompt(round, peer_name, peer_last_text, user_injection, resume_after_halt)`

```
[Round N] [User directive — address this first]: <directive>   ← only if queued
Your peer (<peer_name>) just said:

---
<last completed peer turn text>
---

Respond per your role. End with a <verdict> trailer.
```

**Resume prefix** (prepended when `resume_after_halt=True`):

```
[Note: your previous in-flight response was cancelled by the user before completion.
Disregard whatever you were drafting and respond fresh to the instructions below.]
```

The resume prefix is consumed on the **first turn after a halt** only. `_resume_after_halt` is set to `False` immediately after being read, regardless of whether the turn completes or is interrupted again.

### 4.4 Peer text selection

`_last_turn_for(actor)` returns the most recent **completed** turn for the given actor. Interrupted turns are skipped. This ensures an interrupted turn's partial output is never visible to the peer's prompt.

If no completed peer turn exists (e.g. C-1 was interrupted before X-1 ran), `build_first_turn_prompt` is used again on resume.

### 4.5 Directive injection

Directives accumulate in `_pending_directives: dict[str, list[str]]` — one queue per actor (`"claude"`, `"codex"`). A directive targeted at `"both"` is appended to both queues.

At turn start, the full queue for the active actor is consumed: all queued directives are joined with `"\n"` into a single injection block. The queue is cleared immediately after consumption. Directives are never carried forward to a subsequent turn.

### 4.6 Streaming and chunk handling

ACE iterates the agent's async generator. Each chunk is one of:

| `chunk.kind` | Action |
|---|---|
| `"text"` | Append to `turn.text`; broadcast `turn_chunk` to WebSocket |
| `"reasoning"` | Append to `turn.reasoning`; broadcast `turn_chunk` to WebSocket |
| `"done"` | Extract `tokens_in`, `tokens_out`, `session_id`/`thread_id` from metadata |

If `_halt_requested` is set mid-stream: `agent.interrupt()` is called once, then ACE continues iterating with `continue` (not `break`) to drain the pipe naturally. Chunks received after the halt flag is set are discarded — not appended to `turn.text`, not broadcast.

---

## 5. Verdict Protocol

### 5.1 Format

Each turn (except C-1) must end with exactly one verdict trailer on its own line:

```
<verdict>AGREE</verdict>
<verdict>DISAGREE</verdict>
<verdict>REVISED</verdict>
```

ACE parses via regex: `r"<verdict>\s*(AGREE|DISAGREE|REVISED)\s*</verdict>"` (case-insensitive).

### 5.2 Semantics

| Verdict | Emitter | Meaning | ACE action |
|---|---|---|---|
| `PROPOSAL` | Producer (turn 1 only) | Initial proposal — no verdict trailer; ACE does not parse a verdict from the first producer turn | No action; loop continues to critic |
| `AGREE` | Critic | Critic accepts producer's last response; goal is satisfied | Close session; `end_reason = "convergence"` |
| `AGREE` | Producer | Producer accepts critic's last point | No convergence effect; loop continues |
| `DISAGREE` | Either | Position held; critique or defense rejected | Continue loop |
| `REVISED` | Either | Work or critique updated in light of peer response | Continue loop |

**The critic's AGREE is the sole convergence signal**, regardless of which agent holds the critic role. The producer's AGREE has no mechanical effect on session state.

### 5.3 Missing verdict

If ACE parses no verdict from a completed turn (malformed output, agent truncation), `turn.verdict` is `None`. ACE treats a missing verdict from the critic the same as `DISAGREE` — the loop continues. A missing verdict from the producer on turn 1 is expected and correct.

---

## 6. Convergence Conditions

A session transitions to `done` when any of the following is true, checked in this order at the end of each critic turn:

| Condition | `end_reason` | Check |
|---|---|---|
| Critic emits `AGREE` | `"convergence"` | `actor == critic_actor and turn.verdict == "AGREE"` |
| Session token budget exhausted | `"token_limit"` | `_max_tokens_per_session and _session_tokens >= _max_tokens_per_session` |
| Round limit reached | `"round_limit"` | `self.round >= self._round_limit and actor == critic_actor` |

Checks are evaluated after each critic turn only — producer turns do not trigger terminal evaluation.

**Halt timeout** is a separate convergence path:

| Condition | `end_reason` |
|---|---|
| Halted session not resumed within `halt_timeout_secs` | `"expired"` |

Halt timeout is implemented as an `asyncio.Task` created in `stop()` and cancelled in `resume()`. It fires `_halt_timeout_task()` which transitions state to `done` and emits `session_end`.

---

## 7. Halt and Resume

### 7.1 Clean halt

Stop arrives between turns (no agent streaming). `stop()` sets `state = "halted"` and `_halt_requested = True`. No interrupt is sent. On `resume()`, the peer of the last completed turn goes next.

### 7.2 Mid-stream halt

Stop arrives while an agent is streaming. `stop()` sets `state = "halted"` and `_halt_requested = True`. ACE's stream loop detects the flag on the next chunk, calls `agent.interrupt()` once, then continues draining with `continue`. The interrupted turn:

- Stays in `Session.turns` with `interrupted=True`
- Is **never** fed into any agent's next prompt (`_last_turn_for` filters it out)
- Is **never** broadcast as `turn_end` — it receives `turn_cancel` instead
- Does **not** increment `_claude_completed` or `_codex_completed`
- Does **not** increment `round`
- Retains its original turn ID permanently

On `resume()`, `_interrupted_agent` identifies which agent was mid-stream. That same agent runs again. `_resume_after_halt = True` prepends the disregard notice to its next prompt.

### 7.3 Phantom message problem

When Claude is interrupted, the Claude SDK session has already received the in-flight prompt as a user message. Rolling back is not possible — the SDK offers no message-level rollback. The resume prefix notice ("disregard whatever you were drafting") is the mitigation. If an agent references the cancelled content anyway, tighten the prefix wording.

Codex's subprocess is killed on interrupt. The thread ID is preserved. On `codex exec resume`, the server-side Codex session has the prior prompt in its thread history but no response. The resume prefix handles this the same way.

This is an accepted trade-off. Disconnect/reconnect would defeat persistent-session continuity, which is more valuable.

---

## 8. Arbitration Semantics

ACE does not arbitrate on content. It arbitrates on **process**:

- Only Codex can close the session (convergence authority)
- Neither agent can skip a turn or respond twice in a row
- Neither agent sees the full transcript — each sees only the peer's last message
- Neither agent knows the other's system prompt
- The user cannot inject content during an active turn — only while halted

This is a bounded autonomy model. The agents reason freely within their turns. ACE enforces the structure around those turns. The structure is the control plane.

---

## 9. Memory and Context Boundaries

| Boundary | Rule |
|---|---|
| What Claude sees per turn | Its own full session history (via SDK) + the peer's last completed turn text, prepended with round label and optional directive |
| What Codex sees per turn | Its own full thread history (via CLI resume) + the peer's last completed turn text, prepended with round label and optional directive |
| What neither agent sees | The other agent's system prompt, reasoning blocks, the full prior dialogue, or any other agent's turn history |
| What the user sees | Everything — all turn text, all reasoning blocks, all verdicts, all directives, interrupted partial output |
| What JSONL captures | Everything — every event, every payload, every partial turn |

ACE passes `last_peer_turn.text` only — not `last_peer_turn.reasoning`. Reasoning blocks are observable to the user but are not part of the peer-to-peer dialogue.

---

## 10. Observability Model

Every state transition and data event in ACE produces two outputs simultaneously:

1. **JSONL event** — appended to `~/.kollab/sessions/<session_id>.jsonl` via `TranscriptLog`. Flushed on every write. File stays open across halt/resume cycles. Closed only on terminal state or shutdown.

2. **WebSocket broadcast** — sent to all connected browser clients via `_broadcast()`. Fire-and-forget. Dead connections are pruned on send failure.

### 10.1 Event taxonomy

| JSONL `kind` | Trigger | Key payload fields |
|---|---|---|
| `session_start` | `start()` called | `goal`, `session_number` |
| `turn_start` | Turn begins | `turn_id`, `actor`, `role`, `round` |
| `turn_end` | Turn completes normally | `text`, `reasoning`, `verdict`, `thread_id`, `duration_ms` |
| `turn_interrupted` | Turn cancelled mid-stream | `text` (partial), `reasoning` (partial), `thread_id` |
| `user_input` | Directive received | `text`, `target` |
| `session_end` | Terminal state reached | `reason` |

### 10.2 WebSocket message taxonomy

All message types actually broadcast by `ace.py`:

| `type` | Trigger | Key fields |
|---|---|---|
| `state` | Any state transition | `state`, `round`; on `fanning_out` also includes `session_number`, `session_id`, `claude_model`, `codex_model`, `claude_role`, `round_limit` |
| `turn_start` | Turn begins | `turn_id`, `actor`, `role`, `round`, `model` |
| `turn_chunk` | Streaming chunk arrives | `turn_id`, `kind` (text/reasoning/done), `content` |
| `turn_end` | Turn completes | `turn_id`, `actor`, `verdict`, `duration_ms`, `text`, `summary`, `session_id` |
| `turn_cancel` | Interrupted turn | `turn_id` |
| `session_done` | Terminal state | `reason`, `session_id`, `session_number`, `round_limit` |
| `error` | Unhandled exception in turn loop (emitted by `server.py`) | `message` |

Note: `turn_end` includes a `summary` field — this is the per-turn TL;DR text extracted from `<tldr>` tags in the agent output. The UI uses this for the ARC session summary view. If no `<tldr>` tag is present, `summary` is an empty string.

### 10.3 Observability properties

- **Turn IDs are stable** — an interrupted turn's ID appears in `turn_cancel` and in the JSONL `turn_interrupted` event. It never appears in `turn_end`. The next turn of the same actor gets a new, incremented ID.
- **No silent drops** — every chunk that reaches ACE before the halt flag is set is broadcast and appended. After the flag, chunks are discarded but the drain loop runs to completion.
- **Replay is exact** — the JSONL log contains all information needed to reconstruct the full session UI state, including interrupted turns, directives, and reasoning blocks.
- **Reasoning is not peer input** — reasoning blocks are observable to the user and logged to JSONL, but are never included in the peer's prompt. They are metadata on the turn, not part of the dialogue.
- **Per-turn TL;DR (summary)** — if the agent includes a `<tldr>...</tldr>` block in its output, ACE extracts it into `turn.summary`. This is logged to JSONL and broadcast in `turn_end`. The UI uses these summaries to build the ARC session summary view (a compact synthesis of the session's arc). Turns without a `<tldr>` tag have an empty `summary` field and are omitted from the ARC view.

---

## 11. Error Handling

| Failure | Behaviour |
|---|---|
| Agent turn raises an exception | Caught in `_run_session` / `_resume_loop`; broadcast as `error` message to UI; session not closed automatically |
| `agent.interrupt()` raises | Caught with bare `except Exception`; logged at WARNING; drain loop continues |
| JSONL write fails | Not caught — will surface as an unhandled exception in the turn loop (treated same as agent exception above) |
| WebSocket send fails | Dead client pruned from `_ws_clients`; other clients unaffected |
| Halt timer task cancelled | `asyncio.CancelledError` caught inside `_halt_timeout_task`; returns silently |

ACE does not implement retry logic for agent failures. If an agent call fails, the error surfaces in the UI and the user decides whether to resume or abandon the session.

---

## 12. Configuration Contract

ACE reads the following fields from `Config` at session construction. Changes to config after session start have no effect on the running session.

| Field | Used for |
|---|---|
| `claude_binary` | Claude agent CLI path |
| `claude_model` | Claude model string |
| `claude_workdir` | Claude agent CWD |
| `codex_binary` | Codex CLI path |
| `codex_model` | Codex model string |
| `codex_workdir` | Codex agent CWD |
| `round_limit` | Max rounds before `round_limit` terminal state |
| `halt_timeout_secs` | Auto-expiry timer on halt (0 = disabled) |
| `mcp_filesystem_enabled` | Whether to pass filesystem MCP config to Claude |
| `mcp_filesystem_paths` | Allowed paths for filesystem MCP |

Per-session overrides also accept `claude_role` (`"producer"` | `"critic"`) — determines which role Claude takes and assigns the inverse to Codex. Defaults to `"producer"` if not specified.

Per-session overrides (`SessionOverrides`) take precedence over config fields for `round_limit`, `claude_model`, `codex_model`, `max_tokens_per_turn`, and `max_tokens_per_session`.
