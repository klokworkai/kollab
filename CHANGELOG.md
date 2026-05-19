# Changelog

All notable changes to koll♠b are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- REST API for headless session control (`GET /api/session`, `POST /api/session/start`, `POST /api/session/stop`, `POST /api/session/resume`, `POST /api/session/directive`)
- `api_key` bearer token auth for API endpoints (empty = no auth, backward compatible)
- Webhook emission layer (`webhooks.py`) — fire-and-forget, never blocks session
- 8 webhook event types: `session_start`, `turn_end`, `disagreement`, `convergence`, `halt`, `resume`, `directive`, `session_end`
- Slack incoming webhook support with automatic Block Kit payload shaping
- `[webhooks]` TOML config section with `enabled`, `targets`, `slack_targets`, `events`, `timeout_secs`
- `httpx` dependency for async webhook delivery
- OSS prep: `LICENSE` (Apache 2.0), `CONTRIBUTING.md`, `CHANGELOG.md`, `.github/ISSUE_TEMPLATE/`
- Architecture diagram (`docs/kollab_architecture_v5.svg`) — 5-layer validated against source
- Session lifecycle sequence diagram (`docs/kollab_sequence_v1.svg`)
- Formal specs: `specs/ace-orchestration.md`, `specs/ace-api-webhooks.md`
- Example session placeholders: `examples/` with `EXAMPLES-PLAN.md` and per-pattern subdirectories

## [2.0.0] — 2026-04

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

## [1.0.0] — 2026-01

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
