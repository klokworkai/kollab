# Changelog

All notable changes to koll♠b are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- REST API for headless session control (`GET /api/session`, `POST /api/session/stop`, `POST /api/session/resume`, `POST /api/session/input`)
- `api_key` bearer token auth for all `/api/*` endpoints — empty string disables auth, backward compatible with local browser use
- `GET /api/session` endpoint returning current session state for programmatic polling
- `MODEL_ALIASES` in `config.py` for server-side short-label resolution (`sonnet`, `haiku`, `opus`, `mini`)
- `httpx` dependency for async webhook HTTP delivery
- Full test suite for API auth (`tests/test_api_auth.py`)
- OSS prep: `LICENSE` (Apache 2.0), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `NOTICE`
- `.github/ISSUE_TEMPLATE/` and `PULL_REQUEST_TEMPLATE.md`
- Architecture diagram (`docs/kollab_architecture_v5.svg`) — 5-layer, validated against source
- Session lifecycle sequence diagram (`docs/kollab_session_lifecycle_v3.svg`) — 4-lane sequence covering goal fan-out, verdict loop, halt, directive injection, and resume
- Formal specs: `specs/ace-orchestration.md`, `specs/ace-api-webhooks.md`
- Example sessions: `examples/` with worked examples for convergence, critique loop, directive injection, mid-stream halt, and round limit
- `ROADMAP.md` — planned and possible features

### In Progress
- Webhook emission layer (`webhooks.py`) — implemented, not yet end-to-end tested; 8 event types, Slack Block Kit support, fire-and-forget async delivery
- `[webhooks]` TOML config section: `enabled`, `targets`, `slack_targets`, `events`, `timeout_secs`
- Slack URL auto-detection — Slack URLs moved from `targets` to `slack_targets` at config load
- Unit tests for webhook delivery (`tests/test_webhooks.py`) — written, not yet validated against live targets
- Webhooks section in Configure modal (`app.js`) — parked pending end-to-end validation of emission layer

## [1.0.0] — 2026-04

### Added
- Readonly replay — completed sessions reconstructed from JSONL in the history pane
- Tab persistence across browser refresh via `localStorage`
- Session delete from history pane (permanent, confirm modal)
- Mid-stream halt with `interrupt()` — partial turn preserved as observable artifact, never fed back into prompts
- Directive queue per actor — multiple directives accumulate while halted, consumed on next turn
- `DIRECTIVE → CLAUDE / CODEX / CLAUDE, CODEX` cards rendered in UI and JSONL
- Halt timeout with auto-expire (`halt_timeout_secs`, default 1800s)
- Export endpoint — full-fidelity markdown transcript including reasoning blocks, verdicts, thread IDs
- About page (`/about`) with architecture overview and how-to guide
- Light/dark theme toggle persisted to both `localStorage` and `config.toml`
- Collapse-all / expand-all toggle for turn cards
- Turn ID badge with truncated thread ID (e.g. `C-1 · sess_a1b2c3d4`)
- Round counter display in session status strip

### Changed
- README restructured: "Why koll♠b exists", "Why not agents?", ACE framed as reconciliation control plane
- Config modal covers all fields including MCP and logging

### Fixed
- Interrupted turn IDs now stable for session lifetime (no decrement, no renumber)
- Transcript file stays open across halt/resume cycles (only closes on terminal state)

## [0.1.0] — 2026-01

### Added
- Core dialogue loop: goal fan-out, producer/critic roles, verdict trailer parsing
- ACE session state machine (`idle → fanning_out → claude_turn ⇄ codex_turn → done`)
- Streaming turn cards with Claude (orange) and Codex (blue) color coding
- Verdict pills: AGREE, DISAGREE, REVISED
- Collapsible reasoning blocks per turn
- JSONL append-only event log per session
- TOML config at `~/.kollab/config.toml`
- History pane with filter squares (green/amber/red) and session rows
- Stop button (clean halt between turns)
- Round limit enforcement
- Claude Agent SDK integration with filesystem MCP
- Codex subprocess integration (`codex exec resume <thread_id>`)
- MCP packages auto-installed to `~/.kollab/mcp/` on first run
- Single Dockerfile, `kollab` entry point command
