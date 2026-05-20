# Roadmap

koll♠b is a demo and observability tool — the roadmap stays narrow and focused on making the inter-model dynamic more inspectable and more connectable. No scope creep.

Items are listed in rough priority order. Nothing here is a commitment or a timeline.

---

## Near-term

### Environment variable auth (`KOLLAB_API_KEY`)
The `api_key` bearer token currently lives only in `config.toml`. Add support for reading it from the `KOLLAB_API_KEY` environment variable at startup, with the env var taking precedence. Needed for headless and CI use cases without writing secrets to disk.

### Fix pre-existing test failures
Two tests in `test_prompts.py` assert an old prompt prefix format. Update them to match the current `prompts.py` output.

### Example session transcripts
Populate `examples/` with real session exports covering the five documented patterns: sustained critique loop, clean convergence, directive injection, round limit, and mid-stream halt. Each example includes a `transcript.md`, `session.jsonl`, and `notes.md`.

---

## Integration layer

These live **outside** kollab core as separate adapter projects that consume koll♠b's webhook events. koll♠b ships the webhook emission layer; the adapters are built on top of it.

### Slack adapter
A lightweight Slack app that receives koll♠b webhook events and posts them to a channel. koll♠b already emits Slack-formatted Block Kit payloads natively to any Slack incoming webhook URL — this adapter adds interactive buttons (Stop, Resume, Send directive) that call back to the koll♠b API.

Depends on: `api_key` / `KOLLAB_API_KEY` env var support being in place first.

### GitHub Actions integration
A reusable GitHub Action that starts a koll♠b session against a PR diff, waits for convergence or round limit, and posts the transcript as a PR comment. Useful for adversarial review of architecture decisions, API design, or significant code changes before merge.

Depends on: koll♠b REST API (already built), `api_key` auth, and a koll♠b instance reachable from the Actions runner (local runner or a deployed instance).

### GitHub App
A GitHub App that triggers koll♠b sessions automatically on PR open or label events, without requiring a manually configured Actions workflow. Posts results back to the PR as a check or comment.

---

## Parked (not scheduled)

- **GitHub MCP for Claude** — config fields exist, agent code does not read them. Requires a dedicated design session before implementation.
- **Session rehydration across process restarts** — rekindling both agent sessions days later with full model memory. Requires solving Codex thread ID persistence and Claude SDK session continuity across binary restarts. Not attempted without a prior design session.
- **Continue-session via MD artifact** — export a completed session as markdown, start a new session with `(prior MD) + (add-on goal)`. Cheap to build but not yet on the roadmap.
- **Role swap** — rejected. New session if roles need to change.
