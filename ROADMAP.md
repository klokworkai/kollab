# Roadmap

koll♠b is a tool for Individual Contributors (IC), performing adversarial-collaborative validation between Claude and Codex. The roadmap stays focused on making the inter-model dynamic more inspectable and more connectable. No scope creep.

Items are listed in rough priority order. Nothing here is a commitment or a timeline.

---

## Done

### Core validation loop
Two-agent critique-revision loop with configurable role assignment, goal fan-out, halt/resume, directive injection, verdict protocol, streaming UI, JSONL audit trail, readonly session replay, and markdown export.

### User profile context
`user_profile` config field injected as a labeled `## User Profile` block into both agents' system prompts. Editable textarea in the Configure modal.

### Turn anomaly detection
Completed turns with empty text or a missing verdict trailer are flagged with a visible warning on the turn card instead of a blank badge or stuck placeholder.

### Token budget improvements
Session token cap displayed on the goal card when `max_tokens_per_session` is set. `token_limit` history pill and filter swatch added. `max_tokens_per_turn` removed — it was never enforceable and produced broken turns.

### Codex sandboxing
`codex exec` now runs with `--full-auto` plus `--add-dir` per configured path, replacing `--dangerously-bypass-approvals-and-sandbox`. Write access scoped to `codex_workdir` and configured paths.

### File attachments
Attach files to a session at start — injected into both agents' context via the prompt layer.

### REST API and webhook layer

> ⚠️ **Implemented but not end-to-end validated. Do not use in any workflow until a real integration (GHA or Slack) has been tested and confirmed working. Webhook targets must be configured by editing `~/.kollab/config.toml` directly — there is no UI for this yet.**

Headless session control via REST API. Webhook emission of structured session events to arbitrary HTTP endpoints. Slack incoming webhook format supported. The implementation exists in `server.py` and `webhooks.py` but has not been validated against a live integration target.

Full design spec: [`specs/ace-api-webhooks.md`](specs/ace-api-webhooks.md)

---

## Integration layer

These live **outside** kollab core as separate adapter projects. They depend on the REST API and webhook layer being fully validated first — which has not happened yet.

### Slack adapter
A lightweight Slack app that receives koll♠b webhook events and posts them to a channel, with interactive buttons (Stop, Resume, Send directive) that call back to the koll♠b API.

### GitHub Actions integration
A reusable GitHub Action that starts a koll♠b session against a PR diff, waits for convergence or round limit, and posts the transcript as a PR comment.

### GitHub App
A GitHub App that triggers koll♠b sessions automatically on PR open or label events. Posts results back to the PR as a check or comment.

---

## Possible / planned

- **GitHub MCP for Claude** — config fields exist, agent code does not read them. Requires a dedicated design pass before implementation.
- **Session rehydration across process restarts** — rekindling both agent sessions with full model memory after a restart. Requires solving Codex thread ID persistence and Claude SDK session continuity across binary restarts.
- **Continue-session via MD artifact** — export a completed session as markdown, start a new session with `(prior MD) + (add-on goal)`. Content-fork workflow, not session rehydration.
- **Role swap** — swap producer and critic role assignments between sessions without full reconfiguration.
- **Custom role prompts** — define custom system prompts for each role beyond the built-in producer/critic defaults; assign specific personas, constraints, or review lenses to each agent.
- **Workflow templates** — define a named workflow (e.g. PR review, architecture decision, incident postmortem) and pre-configure role assignments and round limits; launch from the template in one step.
- **API call recording + browser replay** — log the raw API layer (prompt sent, response received, token counts, latency) and replay it in the browser as a reconstructed session.
