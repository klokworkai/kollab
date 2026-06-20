# Changelog

All notable changes to koll♠b are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

## [1.1.0-beta] — 2026-06-20

### Added
- User profile context — `user_profile` config field, injected as a labeled `## User Profile` block ahead of role instructions in both agents' system prompts; editable textarea in the Configure modal (2000 char max)
- Turn anomaly detection — a completed turn with empty text and/or a missing verdict trailer is flagged and surfaced as a visible warning on the turn card, instead of a blank badge or stuck "…" placeholder
- Session token cap shown on the goal card (`token cap: N`) when `max_tokens_per_session` is set for that session — live and in reopened history
- `token_limit` filter swatch and history pill (previously fell back to unstyled raw text)

### Changed
- Codex sandboxing — `codex exec` now runs with `--full-auto` plus `--add-dir <path>` per `mcp_filesystem_paths` entry, replacing `--dangerously-bypass-approvals-and-sandbox`. Write access is scoped to `codex_workdir` + configured paths; read access cannot be fully restricted by kollab (disclaimer shown in Configure modal)
- History pane `halted`/`expired` pills recolored to match their red filter swatch (previously gray)

### Removed
- `max_tokens_per_turn` — never enforceable (neither the Claude Agent SDK nor `codex exec` expose a hard per-call token cap); it was only a soft prompt-text hint that produced degenerate, broken turns at low values. `max_tokens_per_session` (a real, measured budget) is unaffected.

## [1.0.0] — 2026-06

### Added

**Core validation loop**
- Two-agent critique-revision loop with goal fan-out, producer/critic roles, and verdict trailer parsing (`AGREE`, `DISAGREE`, `REVISED`)
- ACE session state machine (`idle → fanning_out → claude_turn ⇄ codex_turn → done`)
- Configurable role assignment per session — either agent can be producer or critic; default is Claude as producer, Codex as critic
- Claude Agent SDK integration with persistent in-process sessions and filesystem MCP
- Codex subprocess integration (`codex exec resume <thread_id>`) with persistent thread continuity across halt/resume
- Mid-stream halt with `interrupt()` — partial turn preserved as observable artifact, never fed back into prompts
- Directive queue per actor — multiple directives accumulate while halted, consumed as one block on next turn
- `DIRECTIVE → CLAUDE / CODEX / CLAUDE, CODEX` cards rendered in UI and JSONL
- Halt timeout with auto-expire (`halt_timeout_secs`, default 1800s)
- Round limit enforcement with configurable per-session override
- Token budget enforcement (`max_tokens_per_turn`, `max_tokens_per_session`)

**UI**
- Streaming turn cards with Claude (orange) and Codex (blue) color coding
- Verdict pills: `AGREE`, `DISAGREE`, `REVISED`; `PROPOSAL` on turn 1
- Collapsible reasoning blocks per turn
- Turn ID badge with truncated thread ID (e.g. `C-1 · sess_a1b2c3d4`)
- Tabbed session view — multiple concurrent sessions, each in its own tab
- History pane with session list, filter squares (green/amber/red), and count
- Readonly replay — completed sessions reconstructed from JSONL in the history pane
- Tab persistence across browser refresh via `localStorage`
- Session delete from history pane (permanent, confirm modal)
- Collapse-all / expand-all toggle for turn cards
- Light/dark theme toggle persisted to `localStorage` and `config.toml`
- Contextual empty state and optimistic Stop button feedback
- Export — full-fidelity markdown transcript including reasoning blocks, verdicts, thread IDs, directives

**Persistence and configuration**
- Append-only JSONL event log per session
- TOML config at `~/.kollab/config.toml`, created on first run with defaults
- Working directories auto-created on first run
- MCP packages auto-installed to `~/.kollab/mcp/` on first run via npm
- Optional file logging (`logging_enabled`, `logging_level`)
- `MODEL_ALIASES` for short-label resolution (`sonnet`, `haiku`, `opus`, `mini`)

**File attachments**
- Attach files to a session at start — staged via `/api/attachments/stage`, adopted on session creation
- Injected into both agents' context via the prompt layer
- Per-file, per-session, and total payload size limits configurable in config

**REST API**
- `POST /api/session` — start a session with goal, optional model/round/token overrides, role assignment, and attachment staging ID
- `GET /api/session` — poll current session state (session_id, state, round, turns_completed, started_at)
- `POST /api/session/stop` / `resume` / `input` — control a running or halted session
- `GET /api/sessions` — list all past sessions from JSONL on disk, sorted newest first
- `GET /api/sessions/{id}` — full event list for a session
- `GET /api/sessions/{id}/export` — download markdown transcript
- `GET /api/sessions/{id}/summary` — ARC summary (turn TL;DRs and end reason)
- `DELETE /api/sessions/{id}` — delete a session and its attachments
- `GET /api/config` / `POST /api/config` — read and update config
- `POST /api/shutdown` — graceful shutdown
- Optional bearer token auth (`api_key` config field; empty = no auth)

**Webhook emission**
- Fire-and-forget async delivery to configured HTTP endpoints
- Slack incoming webhook format auto-detected and shaped as Block Kit
- 8 event types: `session_start`, `turn_end`, `disagreement`, `convergence`, `round_limit`, `halt`, `directive`, `session_end`
- Configurable event filter, timeout, and target lists
- Wired at all ACE event sites — delivery never blocks or affects the session

> ⚠️ **The REST API and webhook layer are implemented but have not been end-to-end tested or validated against any live integration target. Do not rely on them in any workflow. Webhook targets are configured by editing `~/.kollab/config.toml` directly — there is no UI for this yet.**

**OSS prep**
- `LICENSE` (Apache 2.0), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `NOTICE`
- `.github/ISSUE_TEMPLATE/` and `PULL_REQUEST_TEMPLATE.md`
- Architecture diagram (`docs/kollab_architecture_v5.svg`)
- Session lifecycle sequence diagram (`docs/kollab_session_lifecycle_v3.svg`)
- Formal specs: `specs/ace-orchestration.md`, `specs/ace-api-webhooks.md`
- Example sessions: `examples/`
- Single `kollab` entry point command
