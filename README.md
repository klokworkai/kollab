# kollab

> 🧪 **v1.1.0-beta** — kollab is in active development and has not been extensively tested. Bug reports and feedback welcome — open an [issue](https://github.com/klokworkai/kollab/issues) or reach out at [kollab@klokwork.ai](mailto:kollab@klokwork.ai).

**koll♠b** — a structured validation and correction layer for AI-generated proposals, with a full audit trail.

koll♠b runs two AI coding agents — **Claude** (Anthropic) and **Codex** (OpenAI) — through a critique-revision loop on a shared engineering objective. The roles are configurable: either model can be the producer or the critic. Every critique, revision, and concession is streamed live to a browser UI and logged to disk. You don't just get an answer — you get a validated artifact and the complete record of how it got there.

> Independent Contributor (IC) tool. Not for production use, yet.

---

## What kollab does

Two agents, configurable roles, one shared goal. The full validation trace is visible in real time.

1. User submits an engineering objective and assigns roles — producer and critic — to each agent
2. The producer generates an initial proposal
3. The critic reviews it, identifies real gaps, and issues a verdict — `AGREE`, `DISAGREE`, or `REVISED`
4. ACE enforces the critique-revision loop — turn by turn, verdict by verdict — until the proposal passes or the round limit is reached
5. User can halt at any point, inject a directive into one or both agents, and resume
6. Session ends on critic `AGREE`, round limit, or user halt — the full critique trail is exported alongside the final proposal

The product is a **validated proposal with an auditable provenance trail** — not just AI output.

---

## Why koll♠b exists

Most AI-assisted engineering workflows are single-model and unvalidated: you send a prompt, you get output, and you have no independent review, no forced revision, and no record of what tradeoffs were made or what the model didn't challenge itself on. You're asked to trust the output without any basis for that trust.

koll♠b introduces a validation layer. Two independent models work on the same goal with assigned roles — one produces, one critiques — and neither can skip the other's objections. The critic must find substantive flaws or concede. The producer must address real critique or hold its ground with reasoning. Every turn is logged, streamed live, and replayable. The result isn't just an answer — it's a proposal that has been challenged and either survived or been improved by that challenge.

**Three mechanics that make this work:**

- **Structured convergence protocol.** Every turn ends with a `<verdict>` trailer — `AGREE`, `DISAGREE`, or `REVISED`. ACE parses this mechanically. Critic `AGREE` is the sole convergence signal — the critic is the validation arbiter, not a heuristic. You know exactly why the session closed.
- **Human intervention is first-class.** Stop can fire at any point including mid-stream. The partial output is preserved as an observable artifact but never fed back into any agent's prompt. Directive injection is per-actor and queued — multiple directives accumulate, not overwrite. This is a state machine, not a kill switch bolted on after the fact.
- **Observability is structural, not opt-in.** Turn IDs are stable for the session lifetime. Reasoning blocks are separated from response text. Interrupted turns keep their ID and remain visible. Every event is typed, logged to JSONL, and replayable from disk. You can't accidentally make a session un-auditable.

The browser UI is a window into the validation process — a factory tour, not the factory itself. What comes out the other end is a proposal you can trust because you can watch every challenge it faced.

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

**Roles are assigned per session and are configurable:**

Either agent can be assigned the producer or critic role when starting a session. The default is Claude as producer and Codex as critic, but this is reversible in the New Session dialog.

- **Producer.** Writes the initial proposal and refines it under critique. The producer's first turn is always `PROPOSAL` — no verdict on turn 1.
- **Critic.** Reviews the producer's output, finds substantive gaps, and issues a verdict each turn. A single critic `AGREE` closes the session — the critic's sign-off is the validation gate.

**Verdict protocol:**

| Verdict | Meaning |
|---|---|
| `AGREE` | Proposal passes validation — session ends (critic only) |
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

![kollab architecture](docs/kollab_architecture_v5.svg)

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

Observability is what makes the validation trustworthy. A critic `AGREE` means something because you can see every critique that preceded it and every revision it forced. Every decision point in the orchestration is visible:

- Turn IDs (`C-1`, `X-1`, ...) are stable for the session lifetime — interrupted turns keep their ID, completed turns never renumber.
- Reasoning blocks are surfaced per turn alongside the response text.
- Directives are rendered as explicit `DIRECTIVE → CLAUDE / CODEX` cards, not silently injected.
- Interrupted turns are preserved as observable artifacts with a `⏸ interrupted` marker — the partial output is visible but clearly not part of the validated dialogue.
- Every session is replayable from its JSONL log — the history pane reconstructs the full turn sequence from disk.
- Export produces a full-fidelity markdown transcript including reasoning blocks, verdicts, thread IDs, and directives.

---

## REST API and webhooks *(implemented, not validated)*

> ⚠️ **The REST API and webhook layer are implemented in the codebase but have not been end-to-end tested or validated against any live integration target. Do not rely on them in any workflow. They are provided as a foundation for future integration work only.**

A REST API for headless session control exists — start, stop, resume, and poll sessions via HTTP without a browser. A webhook emission layer (`webhooks.py`) fires structured events (`disagreement`, `convergence`, `halt`, `directive`, and others) to any configured HTTP endpoint, with Slack incoming webhooks as a supported target format.

Webhook targets are configured by editing `~/.kollab/config.toml` directly under the `[webhooks]` section. There is no UI for this yet.

Full design spec: [`specs/ace-api-webhooks.md`](specs/ace-api-webhooks.md)

NOTE: The REST API/webhook was layer envisioned at a much earlier stage. But the AI domain/space moves at such a rapid pace that there now exist a wide variety of multi-agent/multi-role orchestrating tools/frameworks before some of the koll♠b's initial ideas could see daylight. These ideas/features still could be implemented in koll♠b with additions/changes at a later date.

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
| `claude_model` | `claude-sonnet-4-6` | Default Claude model. Short aliases (`haiku`, `sonnet`, `opus`) are also accepted. |
| `codex_binary` | `codex` | Path to Codex CLI |
| `codex_model` | `gpt-5.4` | Default Codex model. Short alias `mini` resolves to `gpt-5.4-mini`. |
| `round_limit` | `8` | Max rounds per session |
| `halt_timeout_secs` | `1800` | Auto-expire halted sessions (0 = never) |
| `port` | `8765` | Server port |
| `mcp_filesystem_enabled` | `true` | Give Claude filesystem MCP access |
| `logging_enabled` | `false` | Write logs to `~/.kollab/kollab.log` |

Per-session overrides (role assignment, model, round limit, token budget) are set in the New Session modal.

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

## Roadmap

See [ROADMAP.md](ROADMAP.md).

---

## Status

v1.1.0-beta. Core validation loop, configurable role assignment, halt/resume, directive injection, user profile context, file attachments, session history, streaming, export, and readonly replay are complete. REST API and webhook layer are implemented but not end-to-end validated — see disclaimer above.

This is a beta release. The feature set is stable but has not been extensively tested end-to-end, particularly the latest additions (user profile injection, token-limit history pill, turn anomaly detection, Codex `--full-auto` sandboxing). If something breaks, please [open an issue](https://github.com/klokworkai/kollab/issues).

---

## License

Apache 2.0

---

<p align="center">
  <img src="./kollab/static/assets/kollab-logo.png"/>
</p>
