# ACE API + Webhook Spec

**Status:** Implemented — not end-to-end validated  
**Scope:** Headless API access to kollab sessions + structured webhook event emission  
**Target modules:** `server.py`, `config.py`, `ace.py`, `webhooks.py`

> ⚠️ **The REST API and webhook layer are implemented in the codebase but have not been end-to-end tested or validated against any live integration target. Do not rely on them in any workflow. A Slack or GitHub Actions integration must be built and validated before this can be considered shippable. Webhook targets are configured by editing `~/.kollab/config.toml` directly — there is no UI for this.**

---

## Implementation Status

| Component | Status | Notes |
|---|---|---|
| `api_key` bearer auth | ✅ Implemented | `api_key` config field wired; `require_api_key` dependency on all `/api/*` routes |
| `GET /api/session` | ✅ Implemented | Returns current session state for polling |
| `POST /api/session` explicit response shape | ✅ Implemented | Returns `session_id`, `session_number`, `state` |
| `MODEL_ALIASES` server-side resolution | ✅ Implemented | Short labels resolved in `config.py` |
| `WebhookConfig` nested model | ✅ Implemented | `[webhooks]` TOML section, all fields |
| `webhooks.py` emit function | ✅ Implemented | Fire-and-forget, async, never raises |
| Slack URL auto-detection | ✅ Implemented | Slack URLs moved from `targets` to `slack_targets` at config load |
| Slack Block Kit payload shaping | ✅ Implemented | All 8 event types shaped |
| ACE emit call sites | ✅ Implemented | All 9 emit points wired in `ace.py` |
| Configure modal — Webhooks section | ❌ Not implemented | Not in `app.js`; configure via `config.toml` directly |
| `httpx` dependency | ✅ Implemented | Added to `pyproject.toml` |
| Test coverage — `test_webhooks.py` | ⏳ In progress | Core cases written; not fully validated |
| Test coverage — `test_api_auth.py` | ⏳ In progress | Auth cases written; edge cases pending |
| End-to-end integration (Slack or GHA) | ❌ Not done | Required before this layer is usable |

---

## 1. Problem Statement

kollab is currently browser-only. There is no way to:
- Trigger a session programmatically from an external system
- Subscribe to reasoning events (disagreements, convergence, halts) as they happen
- Route those signals to Slack, Teams, CI pipelines, or any downstream system

This spec adds two capabilities:
1. **Headless API** — start, stop, resume, and direct sessions via HTTP without a browser
2. **Webhook emission** — ACE emits structured HTTP POST events on configurable triggers; Slack incoming webhooks are a first-class supported target

These two features are independent. Either can be used without the other.

---

## 2. Headless API

### 2.1 What changes

The existing REST endpoints (`POST /api/session`, `POST /api/session/stop`, etc.) already exist and already work. No new endpoints are required for basic headless use.

What is missing:
- API key authentication (the server is currently open, localhost-only by design — headless use may expose it)
- A response shape guarantee for programmatic consumers
- `GET /api/session` for polling current session state

### 2.2 Authentication

Add optional API key auth. When `api_key` is set in config, all `/api/*` requests must include:

```
Authorization: Bearer <api_key>
```

If `api_key` is empty string (default), auth is disabled — existing local browser use is unaffected.

**Config field to add:**
```toml
api_key = ""   # empty = no auth required
```

**Implementation:** FastAPI dependency `require_api_key` injected on all `/api/*` routes. Returns HTTP 401 if key is set and header is missing or wrong. Browser WebSocket at `/ws` is exempt — it is always local.

### 2.3 Endpoints

| Method | Path | Status | Notes |
|---|---|---|---|
| `POST` | `/api/session` | existing | Start a new session |
| `POST` | `/api/session/stop` | existing | Halt the active session |
| `POST` | `/api/session/resume` | existing | Resume a halted session |
| `POST` | `/api/session/input` | existing | Send a directive to a halted session |
| `GET` | `/api/session` | **add** | Get current session state |
| `GET` | `/api/sessions` | existing | List all past sessions |
| `GET` | `/api/sessions/{id}` | existing | Get full event log for a session |
| `GET` | `/api/sessions/{id}/export` | existing | Download markdown transcript |
| `DELETE` | `/api/sessions/{id}` | existing | Delete a session |
| `GET` | `/api/config` | existing | Get current config |
| `POST` | `/api/config` | existing | Update config |
| `POST` | `/api/shutdown` | existing | Graceful shutdown |

### 2.4 GET /api/session

Returns current session state for polling. No request body.

**Response — active session:**
```json
{
  "session_id": "sess_a1b2c3d4",
  "session_number": 12,
  "state": "codex_turn",
  "round": 3,
  "goal": "Design a retry policy for the payments service",
  "turns_completed": 5,
  "started_at": "2026-05-18T21:00:00.000Z"
}
```

**Response — no active session:**
```json
{
  "session_id": null,
  "state": "idle"
}
```

`turns_completed` = count of non-interrupted turns in `Session.turns`. `started_at` = ISO timestamp from the `session_start` JSONL event.

### 2.5 POST /api/session — explicit response shape

**Request:**
```json
{
  "goal": "Design a retry policy for the payments service",
  "round_limit": 6,
  "claude_model": "claude-sonnet-4-6",
  "codex_model": "gpt-5.4",
  "max_tokens_per_session": null
}
```

All fields except `goal` are optional. `claude_model` and `codex_model` accept the short label (`sonnet`, `haiku`, `mini`) or the full model string. If a short label is passed, resolve it via `MODEL_MATRIX` in `app.js` — or define the same mapping in `config.py` as `MODEL_ALIASES: dict[str, str]` so server-side callers don't need the browser.

**Response:**
```json
{
  "session_id": "sess_a1b2c3d4",
  "session_number": 12,
  "state": "fanning_out"
}
```

### 2.6 Headless usage pattern (polling, no webhooks)

```
POST /api/session                    → get session_id
loop: GET /api/session               → poll state every 2–5s
      until state in [done, halted]
GET  /api/sessions/{session_id}      → read full event log
GET  /api/sessions/{session_id}/export → download markdown transcript
```

---

## 3. Webhook Emission

### 3.1 Design principles

- Webhooks are **fire-and-forget**. A failed delivery does not halt the session or cause retries.
- The webhook call is made **after** the event is written to JSONL and broadcast to WebSocket clients — always the last step in event processing.
- Webhook delivery is **async and non-blocking** — must not add latency to the turn loop.
- **Slack incoming webhooks** are a first-class target. If a target URL matches `hooks.slack.com`, the payload is automatically shaped as Slack Block Kit. No Slack SDK or extra config needed.
- Standard JSON targets and Slack targets can coexist in the same config.

### 3.2 Config fields to add

Added as a nested `[webhooks]` section in `config.toml`:

```toml
[webhooks]
enabled = false
targets = []         # list of URLs — receive standard JSON payload
slack_targets = []   # list of Slack incoming webhook URLs — receive Block Kit payload
events = [           # event types to emit; all enabled by default
  "session_start",
  "turn_end",
  "disagreement",
  "convergence",
  "round_limit",
  "halt",
  "directive",
  "session_end"
]
timeout_secs = 5     # per-request HTTP timeout; failures logged, not fatal
```

At config load time: if any URL in `targets` matches `https://hooks.slack.com/`, move it to `slack_targets` and log a warning. This prevents raw JSON being posted to a Slack endpoint.

### 3.3 Event types

| Event type | Trigger | Terminal? |
|---|---|---|
| `session_start` | Session begins, both agents receive goal | No |
| `turn_end` | Any turn completes with a verdict | No |
| `disagreement` | `turn_end` where `verdict == DISAGREE` | No |
| `convergence` | Codex emits AGREE; session closes | Yes |
| `round_limit` | Session closes due to round limit | Yes |
| `halt` | Session halted (clean or mid-stream) | No — may resume |
| `directive` | User injects directive while halted | No |
| `session_end` | Any terminal state reached | Yes |

`convergence` and `round_limit` are emitted **before** `session_end`. `session_end` is always the last event emitted for a session. A caller subscribing only to `session_end` gets notified on all terminal outcomes via the `end_reason` field.

`disagreement` is a subset of `turn_end`. If both are enabled, both are emitted on a DISAGREE turn. A caller who only wants disagreements should enable `disagreement` and disable `turn_end`.

### 3.4 Standard JSON payload

Posted as `Content-Type: application/json` to all URLs in `webhooks.targets`.

All fields listed below are always present when applicable to the event type. Fields not applicable to an event are **omitted** (not null, not empty — absent).

```json
{
  "event": "disagreement",
  "session_id": "sess_a1b2c3d4",
  "session_number": 12,
  "timestamp": "2026-05-18T21:04:32.118Z",
  "round": 3,
  "goal": "Design a retry policy for the payments service",
  "turn_id": "X-2",
  "actor": "codex",
  "role": "critic",
  "verdict": "DISAGREE",
  "turn_text": "The proposed retry policy has no jitter..."
}
```

**Field presence by event type:**

| Field | session_start | turn_end | disagreement | convergence | round_limit | halt | directive | session_end |
|---|---|---|---|---|---|---|---|---|
| `event` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `session_id` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `session_number` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `timestamp` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `round` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — | ✓ |
| `goal` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `turn_id` | — | ✓ | ✓ | ✓ | — | — | — | — |
| `actor` | — | ✓ | ✓ | ✓ | — | — | — | — |
| `role` | — | ✓ | ✓ | ✓ | — | — | — | — |
| `verdict` | — | ✓ | ✓ | ✓ | — | — | — | — |
| `turn_text` | — | ✓ | ✓ | ✓ | — | — | — | — |
| `directive_text` | — | — | — | — | — | — | ✓ | — |
| `directive_target` | — | — | — | — | — | — | ✓ | — |
| `end_reason` | — | — | — | ✓ | ✓ | — | — | ✓ |

`end_reason` values: `convergence`, `round_limit`, `token_limit`, `halted`, `expired`.

`turn_text` is the full turn text. No truncation in the standard payload. Callers are responsible for handling large payloads.

### 3.5 Slack payload

Posted as `Content-Type: application/json` to all URLs in `webhooks.slack_targets`. Uses [Slack Block Kit](https://api.slack.com/block-kit). `text` field is the fallback for notifications.

`turn_text` and `directive_text` are truncated to **500 characters** in Slack payloads. The `text` field is always ≤ 100 characters.

**disagreement:**
```json
{
  "text": "kollab · disagreement on X-2 (round 3)",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":x: Disagreement — X-2 · Round 3" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Actor:* Codex (critic)" },
        { "type": "mrkdwn", "text": "*Goal:* Design a retry policy for the payments service" },
        { "type": "mrkdwn", "text": "*Verdict:* `DISAGREE`" }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Critique:*\nThe proposed retry policy has no jitter..."
      }
    }
  ]
}
```

**convergence:**
```json
{
  "text": "kollab · convergence reached (session #12)",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":white_check_mark: Convergence — Session #12" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Rounds:* 3" },
        { "type": "mrkdwn", "text": "*Goal:* Design a retry policy for the payments service" }
      ]
    }
  ]
}
```

**round_limit:**
```json
{
  "text": "kollab · round limit reached (session #12)",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":warning: Round Limit — Session #12" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Rounds:* 8 / 8" },
        { "type": "mrkdwn", "text": "*Goal:* Design a retry policy for the payments service" }
      ]
    }
  ]
}
```

**halt:**
```json
{
  "text": "kollab · session #12 halted (round 3)",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":pause_button: Session Halted — #12" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Round:* 3" },
        { "type": "mrkdwn", "text": "*Goal:* Design a retry policy for the payments service" }
      ]
    }
  ]
}
```

**directive:**
```json
{
  "text": "kollab · directive sent to Claude (session #12)",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":speech_balloon: Directive — Session #12" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Target:* Claude" }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Directive:*\nFocus the retry analysis on the payment capture endpoint only."
      }
    }
  ]
}
```

**session_end:**
```json
{
  "text": "kollab · session #12 ended — convergence",
  "blocks": [
    {
      "type": "header",
      "text": { "type": "plain_text", "text": ":checkered_flag: Session Ended — #12" }
    },
    {
      "type": "section",
      "fields": [
        { "type": "mrkdwn", "text": "*Session:* #12 `sess_a1b2c3d4`" },
        { "type": "mrkdwn", "text": "*Reason:* convergence" },
        { "type": "mrkdwn", "text": "*Rounds:* 3" },
        { "type": "mrkdwn", "text": "*Goal:* Design a retry policy for the payments service" }
      ]
    }
  ]
}
```

### 3.6 Slack URL auto-detection

At config load, scan `webhooks.targets` for any URL matching the prefix `https://hooks.slack.com/`. Move matching URLs from `targets` to `slack_targets`. Log a warning per URL moved:

```
WARNING: webhook target 'https://hooks.slack.com/...' moved to slack_targets (Slack requires Block Kit format)
```

---

## 4. Implementation Plan

### 4.1 New file: `kollab/webhooks.py`

All webhook logic lives here. `ace.py` and `server.py` import only the public function `emit`.

```python
async def emit(event_type: str, payload: dict, cfg: Config) -> None:
    """
    Fire-and-forget webhook delivery.
    Delivers to all configured targets concurrently.
    Never raises — all errors are logged.
    """
```

Internal responsibilities:
1. Check `cfg.webhooks.enabled` — return immediately if False
2. Check `event_type in cfg.webhooks.events` — return immediately if not configured
3. Build standard JSON payload from `payload` dict (already shaped by caller)
4. Build Slack Block Kit payload from same `payload` dict
5. POST to all `cfg.webhooks.targets` concurrently (standard JSON)
6. POST to all `cfg.webhooks.slack_targets` concurrently (Slack payload)
7. All posts share the same `asyncio.gather` call with `return_exceptions=True`
8. Log any exceptions or non-2xx responses at WARNING level
9. Total function wall time ≤ `cfg.webhooks.timeout_secs` + small overhead

Use `httpx.AsyncClient` with `timeout=cfg.webhooks.timeout_secs`.

### 4.2 Changes to `ace.py`

Import: `from .webhooks import emit`

Add one `await emit(...)` call at each of the following points. Each call is the **last statement** in its block — after JSONL write (`self._log(...)`) and after WebSocket broadcast (`self._broadcast(...)`).

| Location | `event_type` | Key payload fields |
|---|---|---|
| End of `start()`, after `_broadcast(session_start)` | `"session_start"` | `goal`, `session_id`, `session_number`, `round=0` |
| End of normal turn completion in `run_turn()`, after `_broadcast(turn_end)` | `"turn_end"` | `turn_id`, `actor`, `role`, `verdict`, `turn_text=turn.text`, `round` |
| Same location, if `turn.verdict == "DISAGREE"` | `"disagreement"` | same fields |
| Same location, if `self._done_reason == "convergence"` | `"convergence"` | same fields + `end_reason` |
| After `_broadcast(session_done)` when `state == "done"` | `"session_end"` | `end_reason=self._done_reason`, `round` |
| After `_broadcast(round_limit)` path | `"round_limit"` | `round`, `end_reason="round_limit"` |
| After `_broadcast(halted)` in clean halt path | `"halt"` | `round` |
| After `_broadcast(halted)` in interrupted path | `"halt"` | `round` |
| End of `handle_user_input()` | `"directive"` | `directive_text=text`, `directive_target=target` |

ACE constructs a minimal `payload` dict with the fields above and passes it to `emit()` along with `self._cfg`. `webhooks.py` is responsible for adding `session_id`, `session_number`, `timestamp`, and `goal` to every payload (these are always available from `cfg` context — pass `session_id`, `session_number`, and `goal` as additional args or include in the payload dict at call site).

Simplest approach: ACE builds the full payload dict including all common fields, passes it to `emit()`. `webhooks.py` does not reconstruct — it only shapes the Slack format from the incoming dict.

### 4.3 Changes to `config.py`

Add `WebhookConfig` nested model:

```python
class WebhookConfig(BaseModel):
    enabled: bool = False
    targets: list[str] = []
    slack_targets: list[str] = []
    events: list[str] = [
        "session_start", "turn_end", "disagreement",
        "convergence", "round_limit", "halt",
        "directive", "session_end",
    ]
    timeout_secs: int = 5
```

Add to `Config`:
```python
api_key: str = ""
webhooks: WebhookConfig = WebhookConfig()
```

In `load_config()`, after constructing `cfg`, call a helper `_normalise_webhook_targets(cfg)` that moves Slack URLs from `targets` to `slack_targets`.

In `save_config()`, `model_dump()` serialises `webhooks` as a nested dict — `tomli_w` writes it as a `[webhooks]` TOML section automatically.

### 4.4 Changes to `server.py`

**Add `require_api_key` dependency:**

```python
from fastapi import Depends, Header

async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    if not _cfg.api_key:
        return  # auth disabled
    if authorization != f"Bearer {_cfg.api_key}":
        raise HTTPException(status_code=401, detail="Unauthorized")
```

Apply to all `/api/*` route functions via `dependencies=[Depends(require_api_key)]`. Routes exempt: `/`, `/about`, `/static/*`, `/ws`.

**Add `GET /api/session`:**

```python
@app.get("/api/session", dependencies=[Depends(require_api_key)])
async def get_session_state() -> dict:
    if _session is None:
        return {"session_id": None, "state": "idle"}
    return {
        "session_id": _session.id,
        "session_number": _session.session_number,
        "state": _session.state,
        "round": _session.round,
        "goal": _session.goal,
        "turns_completed": sum(1 for t in _session.turns if not t.interrupted),
        "started_at": _session.turns[0].started_at.isoformat() if _session.turns else None,
    }
```

**Add `MODEL_ALIASES` to `config.py`** for server-side model string resolution:

```python
MODEL_ALIASES: dict[str, str] = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-7",
    "mini":   "gpt-5.4-mini",
}
```

In `start_session()`, resolve `body.claude_model` and `body.codex_model` through `MODEL_ALIASES` before passing to `SessionOverrides`.

### 4.5 Configure modal in `app.js`

Add a **Webhooks** section to the configure modal, styled identically to the existing Logging section (inline toggle + label pattern, 2-col layout).

Fields:
- Enabled toggle (boolean)
- Webhook URLs textarea — label "Webhook targets (JSON)", placeholder "https://your-app.com/hooks/kollab"
- Slack webhook URLs textarea — label "Slack webhook URLs", placeholder "https://hooks.slack.com/services/..."
- Events — one checkbox per event type, 2-col grid
- Timeout — number input, label "Timeout (seconds)", default 5

Textarea values are newline-separated URLs. On save, split by newline, strip whitespace, filter empty lines, send as array.

---

## 5. Error Handling Contract

| Scenario | Behaviour |
|---|---|
| `webhooks.enabled = false` | `emit()` returns immediately, no HTTP calls made |
| Event type not in `webhooks.events` | `emit()` returns immediately |
| Target URL unreachable / timeout | Log WARNING, continue. Session unaffected. |
| Target returns non-2xx | Log WARNING with URL and status code, continue. |
| Empty `targets` and `slack_targets` | `emit()` returns immediately (no-op) |
| Malformed URL in config | Caught at `httpx` call, logged as WARNING, skipped |
| `emit()` raises unexpectedly | Caught at call site in `ace.py` with bare `except Exception`, logged at ERROR |

Webhook failures are **never surfaced to the browser UI** and never interrupt the session.

---

## 6. Dependencies

Add to `pyproject.toml` `dependencies`:

```toml
"httpx>=0.27",
```

Used only in `webhooks.py`. No other module imports `httpx`.

---

## 7. Test Coverage

**`tests/test_webhooks.py`**

- `test_emit_disabled` — `enabled=False`, assert no HTTP calls made
- `test_emit_event_not_configured` — event not in `events` list, assert no HTTP calls
- `test_standard_payload_shape` — emit `disagreement`, assert payload fields match spec
- `test_slack_payload_disagreement` — assert Block Kit structure and field values
- `test_slack_payload_convergence` — assert Block Kit structure
- `test_slack_payload_halt` — assert Block Kit structure
- `test_slack_url_detection` — Slack URL in `targets` → moved to `slack_targets` at config load
- `test_delivery_failure_does_not_raise` — mock target returns 500, assert `emit()` returns normally
- `test_concurrent_delivery` — two targets, assert both receive calls concurrently

Use `httpx.MockTransport` or `respx` for HTTP mocking. No real network calls in tests.

**`tests/test_api_auth.py`**

- `test_no_auth_required_when_key_empty` — `api_key=""`, any request passes
- `test_401_when_key_set_and_header_missing` — `api_key="secret"`, no header → 401
- `test_401_when_key_set_and_wrong_value` — wrong bearer token → 401
- `test_200_when_key_set_and_correct` — correct bearer token → 200

---

## 8. Integration Patterns

kollab's API and webhook layer enables external integrations without any changes to kollab core. The engine is integration-agnostic. The patterns below show what kollab provides and what each adapter needs to do.

In every pattern:
- **kollab provides:** session API, webhook emission, streaming via SSE (once added), JSONL replay
- **The adapter provides:** the surface-specific transport (Slack API, GitHub API, CI runner)
- **The adapter does not reimplement:** orchestration, verdict parsing, halt/resume, agent management

---

### 8.1 Slack Integration

**Purpose:** A team's Slack channel receives live kollab session events — turn completions, disagreements, convergence — and members can stop the session, send a directive, and resume, all from within Slack. No browser required for ambient review workflows.

**Architecture:**

```
kollab (engine)
  │  webhooks (POST per event)
  ▼
Adapter service (your bridge — ~150 lines)
  │  Slack API (post messages, update messages)
  ▼
Slack channel
  │  button clicks → Slack sends action payload to adapter
  ▼
Adapter service
  │  POST /api/session/stop|input|resume
  ▼
kollab (engine)
```

The adapter is a small FastAPI or Flask service. It has two responsibilities:
1. Receive kollab webhooks → format and post to Slack
2. Receive Slack action payloads (button clicks) → call kollab API

**What the adapter needs:**
- A public HTTPS endpoint for Slack to POST action payloads to (ngrok works for dev)
- A Slack app with `incoming webhooks` enabled (for posting messages) and `interactivity` enabled (for receiving button clicks)
- The kollab API base URL and API key
- No Slack OAuth for a single-workspace app — just a bot token

**Scenario: Architecture review with team oversight**

A platform team wants to run a kollab session on a proposed caching strategy and get the result in their `#architecture-review` Slack channel. Any team member should be able to stop the session and inject a constraint if the discussion goes in the wrong direction.

```
1. Engineer triggers session:
   POST /api/session
   { "goal": "Review this caching strategy for the payments service: [design doc URL]",
     "round_limit": 6 }

2. kollab starts → emits webhook: session_start
   Adapter posts to #architecture-review:
   ┌─────────────────────────────────────────────┐
   │ 🔄 kollab session #14 started               │
   │ Goal: Review caching strategy for payments  │
   │ Round limit: 6                              │
   │                          [Stop session]     │
   └─────────────────────────────────────────────┘

3. C-1 completes → emits webhook: turn_end
   Adapter posts:
   ┌─────────────────────────────────────────────┐
   │ C-1 · Claude (producer) · Round 1           │
   │ Proposes write-through cache with 5min TTL  │
   │ on payment confirmations...                 │
   │                          [Stop session]     │
   └─────────────────────────────────────────────┘

4. X-1 completes → emits webhook: disagreement
   Adapter posts:
   ┌─────────────────────────────────────────────┐
   │ ❌ X-1 · Codex (critic) · Round 1 · DISAGREE│
   │ TTL of 5min is too long for fraud detection │
   │ latency requirements. Cache invalidation    │
   │ on payment state change is missing...       │
   │            [Stop + Directive]  [Stop]       │
   └─────────────────────────────────────────────┘

5. Team member clicks [Stop + Directive]:
   Slack opens a modal (text input):
   ┌─────────────────────────────────────────────┐
   │ Send directive to:  ● Claude  ○ Codex  ○ Both│
   │ ┌─────────────────────────────────────────┐ │
   │ │ Consider that fraud checks run async    │ │
   │ │ and do not block the payment response   │ │
   │ └─────────────────────────────────────────┘ │
   │                        [Cancel]  [Send]     │
   └─────────────────────────────────────────────┘

6. Member clicks [Send]:
   Adapter:
     POST /api/session/stop
     POST /api/session/input
       { "text": "Consider that fraud checks run async...",
         "target": "claude" }
     POST /api/session/resume

7. Session resumes → turns continue → convergence
   Adapter posts final message:
   ┌─────────────────────────────────────────────┐
   │ ✅ Session #14 converged — Round 4          │
   │ Goal: Review caching strategy for payments  │
   │                    [View full transcript]   │
   └─────────────────────────────────────────────┘
   [View full transcript] links to kollab UI replay tab
   or to the exported markdown from GET /api/sessions/{id}/export
```

**Key implementation notes for the adapter:**

- Post each webhook event as a **new Slack message** (not an edit) so the channel has a scrollable history of the session
- The [Stop session] button on earlier messages should be disabled/removed once the session is done — update those messages via `chat.update` with the Slack API when `session_end` arrives
- Slack modal for directive input: use `views.open` triggered by the button action; the modal submit calls `POST /api/session/input` then `POST /api/session/resume`
- `turn_text` is truncated to 500 chars in Slack payloads (already handled by the webhook layer) — link to full text in the kollab UI for long turns
- The adapter must store a mapping of `session_id → Slack channel + thread_ts` to update the right messages

**What kollab provides for this pattern:**
- `session_start`, `turn_end`, `disagreement`, `convergence`, `round_limit`, `halt`, `session_end` webhook events with full payload
- Slack-formatted Block Kit payloads automatically for `slack_targets` — the adapter does not need to build Block Kit manually for standard events
- `POST /api/session/stop`, `/input`, `/resume` for the button handlers
- `GET /api/sessions/{id}/export` for the transcript link

---

### 8.2 GitHub Integration

**Purpose:** A kollab session is triggered automatically on a pull request or as a manual workflow step. Claude and Codex review the PR diff and description adversarially. Disagreements are posted as inline review comments. Convergence posts a summary and optionally approves or requests changes.

Two variants: **GitHub Action** (simpler, runs in CI) and **GitHub App** (richer, can react to PR events automatically).

---

#### Variant A: GitHub Action

Simplest integration. A workflow step calls kollab via API, waits for the session to complete, and posts results. Requires a self-hosted or network-accessible kollab instance.

**Scenario: PR review for an infrastructure change**

A platform team requires adversarial AI review of any Terraform PR before human review. The action runs on `pull_request` events targeting `main`.

```yaml
# .github/workflows/kollab-review.yml
name: kollab adversarial review
on:
  pull_request:
    branches: [main]
    paths: ['**.tf', '**.tfvars']

jobs:
  kollab-review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build review goal from PR
        id: goal
        run: |
          DIFF=$(git diff origin/main...HEAD -- '*.tf' | head -200)
          echo "goal=Review this Terraform change for the payments platform: \
            PR #${{ github.event.number }} — ${{ github.event.pull_request.title }}. \
            Diff: ${DIFF}" >> $GITHUB_OUTPUT

      - name: Start kollab session
        id: session
        run: |
          RESPONSE=$(curl -s -X POST $KOLLAB_URL/api/session \
            -H "Authorization: Bearer $KOLLAB_API_KEY" \
            -H "Content-Type: application/json" \
            -d '{"goal": "${{ steps.goal.outputs.goal }}", "round_limit": 4}')
          echo "session_id=$(echo $RESPONSE | jq -r .session_id)" >> $GITHUB_OUTPUT
        env:
          KOLLAB_URL: ${{ secrets.KOLLAB_URL }}
          KOLLAB_API_KEY: ${{ secrets.KOLLAB_API_KEY }}

      - name: Wait for session completion
        run: |
          for i in $(seq 1 60); do
            STATE=$(curl -s $KOLLAB_URL/api/session \
              -H "Authorization: Bearer $KOLLAB_API_KEY" | jq -r .state)
            echo "State: $STATE"
            if [ "$STATE" = "done" ]; then exit 0; fi
            sleep 10
          done
          echo "Timed out" && exit 1
        env:
          KOLLAB_URL: ${{ secrets.KOLLAB_URL }}
          KOLLAB_API_KEY: ${{ secrets.KOLLAB_API_KEY }}

      - name: Post review to PR
        run: |
          # Fetch full session event log
          EVENTS=$(curl -s $KOLLAB_URL/api/sessions/${{ steps.session.outputs.session_id }} \
            -H "Authorization: Bearer $KOLLAB_API_KEY")

          # Extract disagreements and post as review comments
          python3 .github/scripts/kollab_to_github_review.py \
            --events "$EVENTS" \
            --pr ${{ github.event.number }} \
            --repo ${{ github.repository }}
        env:
          KOLLAB_URL: ${{ secrets.KOLLAB_URL }}
          KOLLAB_API_KEY: ${{ secrets.KOLLAB_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

**What `kollab_to_github_review.py` does (~80 lines):**

```
1. Parse JSONL events from the session
2. Extract all turn_end events
3. For DISAGREE turns: post as a GitHub review comment
   (body = turn text, tagged with turn ID and verdict)
4. For the final turn:
   - If end_reason == convergence: approve the PR with summary
   - If end_reason == round_limit: request changes with summary
   - If end_reason == halt/expired: post a neutral comment
```

**Example PR comment posted on disagreement:**

```
🔴 kollab · X-2 · DISAGREE (Round 2)

The proposed security group change opens port 5432 to 0.0.0.0/0.
This violates the platform's network isolation policy for database
tiers. The rule should be scoped to the application subnet CIDR only.

---
Session #14 · sess_a1b2c3d4 · View full transcript: https://kollab.internal/
```

**Example PR approval comment on convergence:**

```
✅ kollab · Session #14 converged (Round 3)

Claude and Codex reached agreement after 3 rounds. The security
group rule was corrected to scope port 5432 to the app subnet CIDR.
No outstanding issues.

---
View full transcript: https://kollab.internal/
```

---

#### Variant B: GitHub App

Richer integration. The app registers for PR events, triggers sessions automatically, and can post inline file-level comments rather than PR-level comments. Requires a GitHub App registration and a persistent service.

**Scenario: Automatic architecture review on design doc PRs**

A team keeps architecture decision records (ADRs) in `docs/adr/`. Any PR that adds or modifies an ADR triggers a kollab session. The result is posted as a structured PR review.

```
1. PR opened: adds docs/adr/0042-retry-strategy.md

2. GitHub sends pull_request.opened webhook to the app service

3. App service:
   - Fetches the ADR file content from the PR
   - Extracts the decision, context, and consequences sections
   - Constructs goal:
     "Review this Architecture Decision Record for the payments platform.
      ADR-0042: Retry Strategy. [full ADR text]
      Evaluate: correctness, completeness, edge cases, failure modes."
   - POST /api/session { goal: ..., round_limit: 5 }
   - Posts a pending status check to the PR:
     ⏳ kollab review in progress...

4. kollab runs session:
   - C-1: Claude proposes assessment of the ADR
   - X-1: Codex disagrees — missing backpressure consideration
   - C-2: Claude revises — adds backpressure section
   - X-2: Codex AGREEs

5. kollab emits webhooks to app service:
   - disagreement (X-1): app stores for review comment
   - convergence (X-2): app triggers final review

6. App service posts GitHub review:
   Files changed: docs/adr/0042-retry-strategy.md

   Inline comment on line 14 (context section):
   ┌─────────────────────────────────────────────────────────┐
   │ 🔴 kollab X-1 · DISAGREE                               │
   │ Backpressure is not addressed. Under sustained load,    │
   │ exponential backoff without a circuit breaker will      │
   │ amplify downstream pressure. Recommend adding a         │
   │ circuit breaker policy to the consequences section.     │
   └─────────────────────────────────────────────────────────┘

   PR-level summary comment:
   ┌─────────────────────────────────────────────────────────┐
   │ ✅ kollab · Session #14 converged — Round 2             │
   │                                                         │
   │ 1 disagreement resolved: backpressure / circuit breaker │
   │ Final verdict: AGREE                                    │
   │                                                         │
   │ View full transcript → https://kollab.internal/         │
   └─────────────────────────────────────────────────────────┘

   Status check updated:
   ✅ kollab review — converged (2 rounds)

7. Human reviewer sees:
   - The specific disagreement as an inline comment on the relevant lines
   - The resolution summary at the PR level
   - A green status check
   - A link to the full kollab session transcript for deep review
```

**What the GitHub App needs beyond kollab:**
- GitHub App registration (webhook receiver, PR read/write permissions, checks write permission)
- A persistent service to receive GitHub webhooks and kollab webhooks
- `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` to post the review
- `POST /repos/{owner}/{repo}/statuses/{sha}` to update the status check
- Mapping of `session_id → PR number + repo` (in-memory or lightweight store)

**What kollab provides for this pattern:**
- `disagreement` webhook with full `turn_text` for inline comment body
- `convergence` / `round_limit` / `session_end` for final review decision
- `GET /api/sessions/{id}` for full event log
- `GET /api/sessions/{id}/export` for the transcript link
- `POST /api/session` with `goal` as the full ADR/diff text

---

### 8.3 What kollab is not responsible for in integrations

- OAuth flows (Slack app install, GitHub App auth) — handled by the adapter
- Storing session-to-surface mappings (which PR → which session) — handled by the adapter
- Rendering turn content in surface-specific formats — handled by the adapter (kollab provides raw text; Slack Block Kit shaping is automatic for `slack_targets` only)
- Rate limiting or queuing multiple simultaneous session requests — kollab is single-session; the adapter must serialise requests or check session state before starting a new one
- Webhook retry / guaranteed delivery — fire-and-forget; adapters should be idempotent

---

## 9. Out of Scope


The following are explicitly deferred and should not be implemented as part of this spec:

- Webhook delivery retries or guaranteed delivery
- Webhook payload signing (HMAC-SHA256)
- Per-target event filtering (all targets receive the same configured event set)
- Webhook delivery log / UI for delivery status
- Streaming payloads (events fire at turn completion, not token-by-token)
- Multiple simultaneous sessions (single-session constraint inherited)
