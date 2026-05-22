# Roadmap

koll♠b is a demo and observability tool — the roadmap stays narrow and focused on making the inter-model dynamic more inspectable and more connectable. No scope creep.

Items are listed in rough priority order. Nothing here is a commitment or a timeline.

---

## In progress

### REST API and webhook layer
Headless session control via REST API. Webhook emission of structured session events (`turn_start`, `turn_end`, `verdict`, `convergence`, `halt`, `directive`, and others) to arbitrary HTTP endpoints. Slack incoming webhooks are a first-class target. The API and emission layer are implemented; field validation and integration testing are ongoing.

Full design spec: [`specs/ace-api-webhooks.md`](specs/ace-api-webhooks.md)

---

## Integration layer

These live **outside** kollab core as separate adapter projects that consume koll♠b's webhook events. They depend on the REST API and webhook layer being fully validated first.

### Slack adapter
A lightweight Slack app that receives koll♠b webhook events and posts them to a channel, with interactive buttons (Stop, Resume, Send directive) that call back to the koll♠b API.

### GitHub Actions integration
A reusable GitHub Action that starts a koll♠b session against a PR diff, waits for convergence or round limit, and posts the transcript as a PR comment. Useful for adversarial review of architecture decisions, API design, or significant code changes before merge.

### GitHub App
A GitHub App that triggers koll♠b sessions automatically on PR open or label events, without requiring a manually configured Actions workflow. Posts results back to the PR as a check or comment.

---

## Parked (not scheduled)

- **GitHub MCP for Claude** — config fields exist, agent code does not read them. Requires a dedicated design session before implementation.
- **Session rehydration across process restarts** — rekindling both agent sessions days later with full model memory. Requires solving Codex thread ID persistence and Claude SDK session continuity across binary restarts. Not attempted without a prior design session.
- **Continue-session via MD artifact** — export a completed session as markdown, start a new session with `(prior MD) + (add-on goal)`. Cheap to build but not yet on the roadmap.
- **Role swap** — rejected. New session if roles need to change.
