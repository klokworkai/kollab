<p align="center">
  <img src="kollab-logo.png"/>
</p>

<p align="center"><em>Two Minds | One Code</em></p>

# koll♠b

koll♠b is a transparent, adversarial-collaborative dialogue engine that pits two AI coding agents — **Claude** (Anthropic) and **Codex** (OpenAI) — against each other on a single goal you define. Every turn, every critique, every revision, and every disagreement is rendered live in your browser as it happens.

The product is the **visibility into the inter-model dynamic** — not the orchestration itself. koll♠b is a demo and observability tool, not a production pipeline.

> ⚠️ Early-stage demo. Not for production use.

---

## How it works — enter ACE, the Adversarial Collab Engine

At the heart of koll♠b is **ACE — the Adversarial Collab Engine**. ACE owns the session state machine, drives every turn, parses verdict trailers, and enforces convergence rules. It doesn't understand what Claude and Codex are saying — it reads the `<verdict>` tag at the end of each turn and acts on it mechanically. When Codex emits `AGREE`, ACE closes the session. When the round limit is hit, ACE stops the loop. The intelligence is in the agents; ACE runs the show.

When you submit a goal, ACE fans it out to both agents simultaneously — each model reads your goal first-hand before seeing any peer output. ACE then alternates turns, feeding each agent only the peer's latest message (not a full transcript replay), so each model reacts to the other in real time.

**Claude is the Producer.** It writes the initial proposal — code, design, argument — and defends or revises it under critique. Claude's first turn is always the `PROPOSAL`.

**Codex is the Critic.** It adversarially reviews Claude's output, finds real flaws, and issues a verdict each turn. The critic's verdict is the only one that matters — a single Codex `AGREE` ends the session regardless of round count.

Each turn ends with a structured verdict trailer:

| Verdict | Meaning |
|---|---|
| `AGREE` | Critique accepted / issue resolved — debate over |
| `DISAGREE` | Position held, critique rejected — continue |
| `REVISED` | Work updated in response to critique — continue |

Sessions end on **convergence** (Codex AGREEs), **round limit** (max rounds without agreement), **token limit** (budget exhausted), or **halt** (you stopped it).

---

## What it does

- Runs **Claude Code** (the CLI agent harness) and **OpenAI Codex** as two long-lived persistent agents
- Sends your goal to both **in parallel** at session start so each forms its own first-hand understanding
- Drives a turn-based producer → critic loop, each turn ending in a `<verdict>` trailer that ACE parses
- Streams the full dialogue live in a browser UI with turn IDs (`C-1`, `X-1`, …), color-coded cards (orange = Claude, blue = Codex), collapsible reasoning blocks, and verdict pills
- Supports **Stop & Resume** at any point — even mid-stream — with optional directed instructions injected into specific agents on resume
- Maintains a **history pane** of all completed sessions with filter by outcome and one-click readonly replay
- Persists open tabs across browser refreshes
- Logs every event as append-only JSONL on disk
- Runs entirely on your machine — no cloud, no accounts, no telemetry

## What it is not

- Not a multi-agent framework, CI tool, or code-review platform
- Not a wrapper around the Claude API or the Claude desktop/web app — it specifically drives **Claude Code**
- Not multi-user, not cloud-hosted, not production-grade

---

## Install

### Prerequisites

- Python 3.11+
- [Claude Code](https://docs.claude.com/en/docs/claude-code) installed and authenticated (`claude --version` works)
- [OpenAI Codex CLI](https://github.com/openai/codex) installed and authenticated (`codex --version` works)
- npm (for MCP filesystem tool, auto-installed on first run)

### From source

```bash
git clone https://github.com/klokworkai/kollab
cd kollab
pip install -e .
```

### Via Docker

```bash
docker build -t kollab .
docker run --rm -p 8765:8765 \
  -v ~/.kollab:/root/.kollab \
  -v ~/.claude:/root/.claude \
  -v ~/.codex:/root/.codex \
  kollab
```

The mounts pass through your existing Claude Code and Codex CLI auth.

---

## Run

```bash
kollab
```

Opens `http://localhost:8765` in your default browser. On first run, MCP packages are auto-installed into `~/.kollab/mcp/`.

If this is your first time, open **⚙ Configure** and verify the binary paths, then click **+ New Session**.

---

## Usage

**Start a session** — click **+ New Session**, type your goal, optionally override the model, round limit, or token budget for this run, then hit Start.

**Stop & Resume** — click **Stop** at any time, including mid-stream. The partial output stays visible as an artifact but is never fed back to either agent. On Resume, optionally select a target and type a directive before continuing.

**Directives** — while halted, select a target (`→ Claude`, `→ Codex`, or `→ Claude, Codex`) and type an instruction. It's injected into that agent's next prompt only and rendered as a `DIRECTIVE →` card in the session.

**History pane** — click **≡** to toggle. Filter by outcome (green = converged, amber = round limit, red = halted/expired). Click any row to open a readonly replay tab. Hover to reveal the × delete button.

**Collapse all** — the `− collapse all` toggle below the goal card collapses every turn card body at once, useful for scanning verdicts across a long session.

**Close all tabs** — the × button left of the tab count closes all inactive tabs without touching an active running session.

**About** — click **?** in the top bar for the full about page and feature guide at `/about`.

**Logs** — `~/.kollab/sessions/<session-id>.jsonl`. Inspect with `jq`.

---

## Configuration

Config lives at `~/.kollab/config.toml`. The **⚙ Configure** modal is the recommended way to edit it.

| Field | Default | Description |
|---|---|---|
| `claude_binary` | `claude` | Path to Claude Code CLI |
| `claude_model` | `claude-sonnet-4-6` | Default Claude model |
| `codex_binary` | `codex` | Path to Codex CLI |
| `codex_model` | `gpt-5.4` | Default Codex model |
| `round_limit` | `8` | Max rounds per session |
| `halt_timeout_secs` | `1800` | Auto-expire halted sessions (0 = never) |
| `port` | `8765` | Server port |
| `sessions_dir` | `~/.kollab/sessions` | JSONL session log directory |
| `mcp_filesystem_enabled` | `true` | Give Claude filesystem MCP access |
| `mcp_filesystem_paths` | `[]` | Allowed paths (empty = agent workdir) |

Per-session overrides (model, round limit, token budget) can be set in the New Session modal without touching the config file.

---

## Architecture

```
┌──────────────────────────────────────────────────────┐
│  Browser (tabbed chat UI + history pane)             │
│   ↕ WebSocket                                        │
│  FastAPI server                                      │
│   ↕                                                  │
│  ACE — Adversarial Collab Engine (ace.py)            │
│   ├── Claude agent (Claude Agent SDK, persistent)    │
│   └── Codex agent (codex CLI subprocess, persistent) │
└──────────────────────────────────────────────────────┘
         │
         ▼
   ~/.kollab/sessions/*.jsonl  (event log)
```

Single Python process. WebSocket for live events. No database — JSONL on disk.

---

## Development

```bash
# install in dev mode
pip install -e ".[dev]"

# run tests
pytest

# run with hot reload
uvicorn kollab.server:app --reload --port 8765
```

---

## License

TBD.

## Status

v2 — active development. Core dialogue loop, halt/resume, history, streaming, and about page complete.
