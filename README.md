# kollab

**koll♠b** — a structured validation and correction layer for AI-generated proposals, with a full audit trail.

koll♠b runs two AI coding agents — **Claude** (Anthropic) and **Codex** (OpenAI) — through a critique-revision loop on a shared engineering objective. One agent produces; the other validates. Every critique, revision, and concession is streamed live to a browser UI and logged to disk. You don't just get an answer — you get a validated artifact and the complete record of how it got there.

> Early-stage demo. Not for production use.

---

## What kollab does

Two agents, fixed roles, one shared goal. The full validation trace is visible in real time.

1. User submits an engineering objective
2. Claude (producer) generates an initial proposal
3. Codex (critic) reviews it, identifies real gaps, and issues a verdict — `AGREE`, `DISAGREE`, or `REVISED`
4. ACE enforces the critique-revision loop — turn by turn, verdict by verdict — until the proposal passes or the round limit is reached
5. User can halt at any point, inject a directive into one or both agents, and resume
6. Session ends on Codex `AGREE`, round limit, or user halt — the full critique trail is exported alongside the final proposal

The product is a **validated proposal with an auditable provenance trail** — not just AI output.

---

## Why koll♠b exists

Most AI-assisted engineering workflows are single-model and unvalidated: you send a prompt, you get output, and you have no independent review, no forced revision, and no record of what tradeoffs were made or what the model didn't challenge itself on. You're asked to trust the output without any basis for that trust.

koll♠b introduces a validation layer. Two independent models work on the same goal with fixed roles — one produces, one critiques — and neither can skip the other's objections. The critic must find substantive flaws or concede. The producer must address real critique or hold its ground with reasoning. Every turn is logged, streamed live, and replayable. The result isn't just an answer — it's a proposal that has been challenged and either survived or been improved by that challenge.

**Three mechanics that make this work:**

- **Structured convergence protocol.** Every turn ends with a `<verdict>` trailer — `AGREE`, `DISAGREE`, or `REVISED`. ACE parses this mechanically. Codex `AGREE` is the sole convergence signal — the critic is the validation arbiter, not a heuristic. You know exactly why the session closed.
- **Human intervention is first-class.** Stop can fire at any point including mid-stream. The partial output is preserved as an observable artifact but never fed back into any agent's prompt. Directive injection is per-actor and queued — multiple directives accumulate, not overwrite. This is a state machine, not a kill switch bolted on after the fact.
- **Observability is structural, not opt-in.** Turn IDs are stable for the session lifetime. Reasoning blocks are separated from response text. Interrupted turns keep their ID and remain visible. Every event is typed, logged to JSONL, and replayable from disk. You can't accidentally make a session un-auditable.

The browser UI is a window into the validation process — a factory tour, not the factory itself. What comes out the other end is a proposal you can trust because you watched every challenge it faced.

---

## ACE — Adversarial Collab Engine

ACE (`ace.py`) is the validation control plane. It owns the session state machine, drives every turn, parses verdict trailers, enforces convergence rules, and manages halt/resume lifecycle. ACE doesn't evaluate the quality of the models' reasoning — it reads the `<verdict>` tag at the end of each turn and acts on it mechanically. The agents do the thinking; ACE enforces the structure around them.

**Session state machine:**

```
idle → fanning_out → claude_turn ⇄ codex_turn → done
                          ↕
                        halted → (resume) → claude_turn | codex_turn
                          ↓
                       expired
```

**Roles are fixed per session:**

- **Claude — Producer.** Writes the initial proposal and refines it under critique. Claude's first turn is always `PROPOSAL` — no verdict on C-1.
- **Codex — Critic.** Reviews Claude's output, finds substantive gaps, and issues a verdict each turn. A single Codex `AGREE` closes the session — the critic's sign-off is the validation gate.

**Verdict protocol:**

| Verdict | Meaning |
|---|---|
| `AGREE` | Proposal passes validation — session ends (Codex only) |
| `DISAGREE` | Critique not addressed — loop continues |
| `REVISED` | Proposal updated in response to critique — loop continues |

**Arbitration semantics:** ACE arbitrates on process, not content. Neither agent can skip a turn, respond twice, or see the other's system prompt. Neither agent sees the full transcript — each sees only the peer's last completed turn. The user cannot inject content during an active turn. Agents reason freely within their turns; ACE enforces the boundaries.

Full orchestration spec: [`specs/ace-orchestration.md`](specs/ace-orchestration.md)

---

## Architecture

koll♠b is five layers. Together they enforce a structured validation protocol with a complete, replayable audit trail.

**Layers:**

- **Browser UI** — vanilla HTML + Tailwind CDN + `app.js`. Tabbed session view, streaming turn cards, history pane, directive input, export. No framework, no build step. The UI surfaces the validation process in real time — every critique, revision, and verdict as it happens.
- **FastAPI server** (`server.py`) — HTTP + WebSocket. Single `/ws` endpoint broadcasts all session events to connected clients. Session history, config, and export endpoints.
- **ACE** (`ace.py`) — the validation engine. Session state machine, turn dispatcher, verdict parser, directive queue (`dict[actor → list[str]]`), halt controller with configurable timeout, prompt builder backed by `prompts.py`.
- **Agents** — `claude_agent.py` wraps the Claude Agent SDK for persistent in-process sessions with filesystem MCP. `codex_agent.py` drives the `codex exec` CLI as a subprocess with session resume via thread ID. Both implement `interrupt()` without tearing down the session.
- **Persistence** — append-only JSONL event log per session (`transcript.py`), TOML config (`config.py`), optional file log (`~/.kollab/kollab.log`).

**Session lifecycle:**

![kollab session lifecycle](docs/kollab_session_lifecycle_v3.svg)

**Key design decisions:**

- **Persistent agent sessions** — both agents hold context across the full run. ACE passes only the peer's latest message, not a full transcript replay. This preserves each agent's independent reasoning thread.
- **Goal fan-out** — the user's goal is sent to both agents in parallel at session start, so each forms a first-hand understanding before any peer output exists. The critic evaluates the goal directly, not through the producer's framing.
- **Mid-stream halt** — `interrupt()` is called on the active agent; ACE continues consuming chunks until the pipe drains naturally. The interrupted turn stays visible in the UI but is never fed back into any agent's prompt.
- **Directive queue** — multiple directives sent while halted accumulate per actor. On resume, all queued directives are concatenated into the next turn's prompt prefix. Directives are rendered explicitly in the UI — never silently injected.
- **No database** — JSONL on disk. Every event (turn start, turn end, verdict, user input, interrupt, session end) is one line of JSON, append-only, flush on every write.

---

## Inspectability

Observability is what makes the validation trustworthy. A Codex `AGREE` means something because you can see every critique that preceded it and every revision it forced. Every decision point in the orchestration is visible:

- Turn IDs (`C-1`, `X-1`, ...) are stable for the session lifetime — interrupted turns keep their ID, completed turns never renumber.
- Reasoning blocks are surfaced per turn alongside the response text.
- Directives are rendered as explicit `DIRECTIVE → CLAUDE / CODEX` cards, not silently injected.
- Interrupted turns are preserved as observable artifacts with a `⏸ interrupted` marker — the partial output is visible but clearly not part of the validated dialogue.
- Every session is replayable from its JSONL log — the history pane reconstructs the full turn sequence from disk.
- Export produces a full-fidelity markdown transcript including reasoning blocks, verdicts, thread IDs, and directives.

---

## API and webhooks *(in progress)*

The REST API for headless session control is implemented — start, stop, resume, and poll sessions via HTTP without a browser. A webhook emission layer (`webhooks.py`) is implemented but not yet end-to-end validated: it fires structured events (`disagreement`, `convergence`, `halt`, `directive`, and others) to any HTTP endpoint, with Slack incoming webhooks as a first-class target.

When fully validated, this enables integration patterns like Slack notifications on convergence, GitHub Actions validation gates on PRs, and CI pipeline critique passes.

Full design spec: [`specs/ace-api-webhooks.md`](specs/ace-api-webhooks.md)

---

## Quick start

```bash
git clone https://github.com/klokworkai/kollab
cd kollab
pip install -e .
kollab
```

Opens `http://localhost:8765`. On first run, configure binary paths via **⚙ Configure** in the top bar.

For full setup instructions including Docker, CLI auth, troubleshooting, and session walkthrough: **[RUNBOOK.md](RUNBOOK.md)**

---

## Configuration

Config lives at `~/.kollab/config.toml`. The **⚙ Configure** modal is the recommended way to edit it.

| Field | Default | Description |
|---|---|---|
| `claude_binary` | `claude` | Path to Claude Code CLI |
| `claude_model` | `claude-sonnet-4-6` | Default Claude model. Short aliases (`haiku`, `sonnet`, `opus`) are also accepted and resolved to full model strings at runtime. |
| `codex_binary` | `codex` | Path to Codex CLI |
| `codex_model` | `gpt-5.4` | Default Codex model. Short alias `mini` resolves to `gpt-5.4-mini`. |
| `round_limit` | `8` | Max rounds per session |
| `halt_timeout_secs` | `1800` | Auto-expire halted sessions (0 = never) |
| `port` | `8765` | Server port |
| `mcp_filesystem_enabled` | `true` | Give Claude filesystem MCP access |
| `logging_enabled` | `false` | Write logs to `~/.kollab/kollab.log` |

Per-session overrides (model, round limit, token budget) are set in the New Session modal.

---

## Development

```bash
pip install -e ".[dev]"
pytest
uvicorn kollab.server:app --reload --port 8765
```

---

## Specs

| Document | Contents |
|---|---|
| [`specs/ace-orchestration.md`](specs/ace-orchestration.md) | ACE state machine, turn lifecycle, verdict protocol, arbitration semantics, observability model |
| [`specs/ace-api-webhooks.md`](specs/ace-api-webhooks.md) | REST API, webhook events and payloads, Slack and GitHub integration patterns |

---

## Status

v1.0.0 — active development. Core validation loop, halt/resume, directive injection, history, streaming, export, and readonly replay are complete. REST API implemented.

**In progress:** Webhook emission layer (implemented, not yet end-to-end validated). GitHub MCP integration and Slack/GitHub adapters are planned.

---

## License

Apache 2.0

---

<p align="center">
  <img src="./kollab/static/assets/kollab-logo.png"/>
</p>
