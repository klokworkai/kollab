# examples/

Real session transcripts demonstrating kollab's core orchestration patterns. Each subdirectory contains:

- A `goal.md` describing the engineering question posed to the session
- A `transcript.md` — the full exported session (markdown export from `GET /api/sessions/{id}/export`)
- A `session.jsonl` — the raw JSONL event log for the session (replay-compatible with the kollab history pane)
- A `notes.md` — what to observe in this example: which turns are interesting, what the disagreement was about, how convergence was reached

## Subdirectories

### `critique-loop/`

A multi-round session where Codex raises substantive objections across several turns and Claude revises. Shows the producer/critic dynamic under sustained disagreement — what DISAGREE and REVISED verdicts look like in practice, how Claude's proposal evolves across rounds, and where the reasoning blocks surface the model's internal thinking.

Suggested goal type: system design decision with multiple valid tradeoffs (retry policy, rate limiting strategy, data model choice).

### `convergence/`

A session that reaches convergence cleanly — Codex AGREEs after a small number of rounds. Shows what a well-formed AGREE verdict looks like, the session_end event in the JSONL, and the full export including reasoning and thread IDs. Good reference for what a "successful" kollab session produces as an artifact.

Suggested goal type: a specific, bounded technical question with a defensible correct answer (e.g. choice of HTTP status code for a specific error condition, naming convention decision, specific algorithm selection).

### `directive-injection/`

A session that is halted mid-stream, a directive is injected targeting one agent, and the session is resumed. Shows the `turn_interrupted` event in the JSONL, the `DIRECTIVE → CLAUDE` card in the transcript, the resume prefix in the agent's next turn, and how the directive changes the direction of the dialogue.

Suggested goal type: any session where the initial direction is plausible but the user wants to add a constraint that wasn't in the original goal (e.g. "now assume the service must run in a resource-constrained environment").

### `round-limit/`

A session that reaches the configured round limit without Codex issuing an AGREE verdict. Shows the `round_limit` session end reason, the amber history pill, and what sustained disagreement looks like across the full round budget.

Suggested goal type: a deliberately contentious design question with valid arguments on both sides.

### `mid-stream-halt/`

A session where Stop is clicked while an agent's turn is actively streaming. Shows the `turn_interrupted` JSONL event, the `⏸ interrupted` marker on the partial turn card, and the subsequent resume turn where the same agent runs again from clean history.

Suggested goal type: any session — the pattern is about the halt timing, not the goal content.

---

## Adding examples

Run a kollab session, then export it:

```bash
# From the UI: completed session → Export button → saves .md transcript
# Raw JSONL is at:
cat ~/.kollab/sessions/<session-id>.jsonl
```

Copy both files into the relevant subdirectory and add a `notes.md` explaining what to look for.
