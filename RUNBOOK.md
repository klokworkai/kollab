# kollab — Runbook

End-to-end instructions: from a clean machine to a running kollab session.

---

## 1. Prerequisites

You need the following before starting. Install anything missing before proceeding.

| Requirement | Check | Install |
|-------------|-------|---------|
| Python 3.11+ | `python3 --version` | [python.org](https://python.org) or `brew install python` |
| Node.js 18+ | `node --version` | [nodejs.org](https://nodejs.org) or `brew install node` |
| Claude Code CLI | `claude --version` | `npm install -g @anthropic-ai/claude-code` |
| OpenAI Codex CLI | `codex --version` | `npm install -g @openai/codex` |
| Git | `git --version` | pre-installed on most systems |

---

## 2. Clone the repo

```bash
git clone https://github.com/klokworkai/kollab.git kollab
cd kollab
```

---

## 3. Authenticate Claude Code

Claude Code requires an Anthropic account with an active API key or a Pro/Max subscription.

```bash
claude
```

On first run Claude will walk you through the auth flow in your browser. Once complete, verify:

```bash
claude --version
# should print a version number, not an auth error
```

Test it works:

```bash
echo "say: hello" | claude --print
```

You should get a short text response back.

---

## 4. Authenticate Codex

Codex requires an OpenAI account with API access.

```bash
codex login
```

Follow the prompts. Once complete, verify:

```bash
codex --version
# should print a version number
```

Test it works:

```bash
echo "say: hello" | codex exec --skip-git-repo-check -
```

You should get a short response. Press Ctrl+C if it waits for input.

---

## 5. Install kollab

```bash
pip3 install -e .
```

This installs all Python dependencies (`fastapi`, `uvicorn`, `claude-agent-sdk`, etc.) and registers the `kollab` command.

Verify:

```bash
kollab --version
# or
python3 -m kollab --version
```

> **Note:** `--help` and `--version` flags are not supported — the entry point starts the server directly. If the command runs and stops without error, the install is wired up correctly. If `kollab` isn't on your PATH, use `python3 -m kollab` everywhere in this runbook.

---

## 6. First run

Start kollab:

```bash
python3 -m kollab
```

This will:
1. Create `~/.kollab/config.toml` with defaults (if it doesn't exist)
2. Start the server on `http://localhost:8765`
3. Open your browser automatically after 1.5 seconds

If the browser doesn't open, go to `http://localhost:8765` manually.

---

## 7. Configure via the UI

On first run, click **⚙ Configure** in the top bar.

Verify or update these fields:

| Field | Default | What to set |
|-------|---------|-------------|
| Claude binary path | `claude` | full path if `claude` isn't on PATH, e.g. `/usr/local/bin/claude` |
| Claude model | `sonnet` | `opus`, `sonnet`, or `haiku` |
| Claude working dir | `~/.kollab/workspace/claude` | leave as-is unless you have a reason |
| Codex binary path | `codex` | full path if `codex` isn't on PATH |
| Codex model | `gpt-5.4` | any model your Codex account can access |
| Codex working dir | `~/.kollab/workspace/codex` | leave as-is |
| Round limit | `8` | max number of rounds before the session auto-ends |
| Port | `8765` | change if 8765 is in use |
| Sessions dir | `~/.kollab/sessions` | where JSONL event logs are written |

Click **Save**. If you see a red error about a binary not found, check that the CLI is installed and the path is correct.

---

## 8. Start a session

1. Click **↻ New Session** in the top bar
2. Type a goal in the textarea — for example:

   > Design a simple rate-limiting strategy for a public REST API. Justify your choices.

3. Click **Start**

What happens next:
- The goal is sent to both Claude and Codex simultaneously
- Claude always takes turn 1 (`C-1`); the role shown depends on your session configuration (producer by default)
- Codex takes turn 2 (`X-1`); the inverse role
- They alternate until one of the stop conditions is met

Each turn appears as a colored card:
- **Orange border** = Claude (producer)
- **Blue border** = Codex (critic)
- The **response ID** (`C-1`, `X-2`, etc.) appears as a small badge top-right of each card
- The **verdict pill** (`AGREE` / `DISAGREE` / `REVISED`) appears when the turn completes
- Click **Reasoning** on any card to expand the model's internal reasoning (if the model produced extended thinking)

The status strip at the bottom shows the current state and round number.

---

## 9. Interrupt a session

Click **Stop** at any time — even mid-stream. The current turn is cancelled cleanly.

Click **Resume** to continue from where the session stopped.

---

## 10. Inject input mid-session

Type in the input box at the bottom and click **Send** (or press Enter).

Your message is queued and delivered to the next agent's turn prompt as a directive, prefixed with `[User directive — address this first]:`. The agent will acknowledge and address it before responding to its peer.

---

## 11. Reference a prior turn

Include a turn ID in your message to pin that turn's text as quoted context for the receiving agent.

Examples:
- `X-2 was wrong about latency — Claude, push back.`
- `Elaborate on C-3.`
- `I disagree with what X-1 said about caching.`

The referenced turn card will briefly highlight in the UI when you send.

---

## 12. Session ends

A session ends when one of these conditions is met:

| Condition | What you see |
|-----------|-------------|
| Critic issues `AGREE` verdict | "✓ Converged." |
| Round limit is reached | "⚠ Round limit reached." |
| You clicked Stop and didn't Resume | "⏹ Session halted." |

Start a new session with **↻ New Session**.

---

## 13. Session logs

Every event (turn start, turn chunk, turn end, user input, error, session start/end) is written as JSONL to:

```
~/.kollab/sessions/<session-id>.jsonl
```

Inspect a log:

```bash
cat ~/.kollab/sessions/<session-id>.jsonl | python3 -m json.tool | less
# or with jq:
jq '.' ~/.kollab/sessions/<session-id>.jsonl | less
```

---

## 14. Run via Docker

> ⚠️ **The Dockerfile has not been tested. The instructions below reflect the intended setup but may require adjustment. Use local install (§5–6) for a reliable setup.**

Build the image:

```bash
docker build -t kollab .
```

Run it, mounting your existing auth directories:

```bash
docker run --rm -p 8765:8765 \
  -v ~/.kollab:/root/.kollab \
  -v ~/.claude:/root/.claude \
  -v ~/.codex:/root/.codex \
  kollab
```

Open `http://localhost:8765` in your browser.

The mounts pass your existing Claude Code and Codex CLI auth through to the container — you don't need to re-authenticate inside it. Session data (JSONL logs, config) is written to `/root/.kollab` inside the container, which maps to `~/.kollab` on your host via the volume mount. Without that mount, session data is lost when the container stops.

---

## 15. Run tests

```bash
pip3 install -e ".[dev]"
python3 -m pytest tests/ -v
```

All 36 tests should pass. These cover config round-trip, verdict parsing, turn ID generation, response reference parsing, prompt building, API auth, and webhook delivery.

---

## 16. Troubleshooting

**Browser doesn't open automatically**
→ Go to `http://localhost:8765` manually. The server is running even if the browser didn't open.

**"Config errors" printed at startup**
→ One or both CLIs aren't on PATH or aren't executable. Open Configure in the UI and set the full binary paths.

**Turn card shows "…" indefinitely**
→ The agent is hanging. Click Stop, check your terminal for errors, then Resume or start a new session.

**`codex` session doesn't resume correctly**
→ The CodexAgent captures the session UUID from the first run's JSONL output. If the UUID wasn't found (the format may vary across codex CLI versions), each `send()` starts a fresh session. The dialogue still works — just without persistent codex memory across turns. Check the terminal for any JSON parse errors.

**Port 8765 already in use**
→ Open Configure, change the port, save, then restart with `python3 -m kollab`.

**`claude-agent-sdk` auth error**
→ Re-run `claude` in your terminal to re-authenticate, then restart kollab.
