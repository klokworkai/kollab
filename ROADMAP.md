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

## Possible / planned

- **GitHub MCP for Claude** — config fields exist, agent code does not read them. Requires a dedicated design session before implementation.
- **Session rehydration across process restarts** — rekindling both agent sessions days later with full model memory. Requires solving Codex thread ID persistence and Claude SDK session continuity across binary restarts.
- **Continue-session via MD artifact** — export a completed session as markdown, start a new session with `(prior MD) + (add-on goal)`. Content-fork workflow, not session rehydration.
- **Role swap** — swap producer and critic roles between sessions without full reconfiguration.
- **Model swap** — replace Claude or Codex with a different model mid-session or at session start without reconfiguring globally.
- **New model support** — add support for additional models beyond Claude and Codex as producers or critics.
- **Custom roles** — define roles beyond producer/critic; assign specific personas, constraints, or review lenses to each agent.
- **Workflow templates** — define a named workflow (e.g. PR review, architecture decision, incident postmortem) and assign models and roles to it; launch a session from the template in one step.
- **Filesystem MCP for all providers** — Auto configured per provider on add, with validaton.
- **File Attachments** — Attach file(s) to agents regardless/independent of MCP.
- **Sesson ARC Summary** — Post session synthesis from turn TL;DRs and Verdicts.
- **API call recording + browser replay** — Re-construct API sessions in kollab browser as a session to observe interations/dialogs.
