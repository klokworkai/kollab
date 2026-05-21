# koll♠b · Examples

Real sessions demonstrating kollab's core orchestration patterns. Each example is a complete record of an actual run — goal, transcript, JSONL log, and annotated notes explaining what to look for.

For a full explanation of how koll♠b works — turn cards, verdict pills, session states, directives, halt/resume — see the **[About page](../kollab/static/about.html)**.

---

## How to read these examples

Each example directory contains:

- **`kollab-example-XX-*.md`** — the annotated notes page: what the session shows, the full verdict sequence, screenshots, and links to the raw files. Start here.
- **`artifacts/`** — screenshots, the exported markdown transcript, and the raw JSONL session log.
  - **`kollab-ex*.png`** — screenshots from the koll♠b UI
  - **`*-transcript.md`** — full session export (all turns, reasoning blocks, verdicts)
  - **`sess_*.jsonl`** — raw JSONL event log, replay-compatible with the koll♠b history pane

To replay a session locally: copy the `.jsonl` file into `~/.kollab/sessions/` and it will appear in the history pane.

---

## Examples

### [`critique-loop/`](critique-loop/kollab-example-01-retry-backoff.md)
**Retry & backoff strategy for a payments API client · Session #13 · `sess_30285e2d` · Converged in 4 rounds**

Codex finds three internal correctness gaps in Claude's proposal — an off-by-one in the retry count, a herd-prone circuit breaker, and a threshold too permissive for the stated goal. Claude revises twice before Codex agrees. Shows the producer/critic dynamic under sustained disagreement: what DISAGREE and REVISED verdicts look like in practice, how the proposal tightens across rounds, and how Codex's critique stays grounded in the proposal's own numbers rather than generic best practices.

---

### [`convergence/`](convergence/kollab-example-02-polling-webhooks-websockets.md)
**Polling vs webhooks vs WebSockets for async mobile notifications · Session #14 · `sess_89ecd22a` · Converged in 2 rounds**

Fast convergence — one DISAGREE, one AGREE. Codex's critique is not about a number but about a wrong architectural assumption: Claude silently assumed a device-only architecture, which invalidated the entire webhook dismissal. Claude concedes completely, restructures the recommendation around client architecture tiers, and Codex agrees with one residual precision note. Shows what clean convergence looks like and how a single assumption-level critique can force a complete reframe rather than a parameter fix.

---

### [`directive-injection/`](directive-injection/kollab-example-03-multitenant-data-model.md)
**Multi-tenant SaaS data model · Session #20 · `sess_6eb85a70` · Converged in 7 rounds**

After X-1 is interrupted, the user injects a directive before resuming: the application must also support cross-tenant project sharing via explicit invitation. The directive card appears inline between X-1 and X-2, visible in the session flow. C-4 absorbs both the directive and Codex's seven-point critique simultaneously. Shows how a mid-session directive enters the dialogue, renders as a `DIRECTIVE → CLAUDE` card, and is acknowledged in the agent's reasoning block before shaping the response.

*Note: shares the same session (`sess_6eb85a70`) as `mid-stream-halt/`. Different framing, same JSONL.*

---

### [`round-limit/`](round-limit/kollab-example-04-monolith-vs-microservices.md)
**Monolith vs microservices for a greenfield B2B SaaS · Session #19 · `sess_69a312af` · Round limit hit (2 rounds)**

Session ends without convergence. Codex issues REVISED on its final turn — the debate was still live when the round limit fired. Shows the amber `⚠ Round limit (2)` pill in the goal card, the `△ Round limit reached (2 rounds).` bottom banner, and the history pane amber pill. Also the first example showing model names in the goal card meta row (`claude-haiku-4-5-20251001 · gpt-5.4-mini · rounds: 2`). Useful as a reference for what a time-boxed design review produces: a map of unresolved disagreements, not a final answer.

---

### [`mid-stream-halt/`](mid-stream-halt/kollab-example-05-multitenant-data-model.md)
**Multi-tenant SaaS data model · Session #20 · `sess_6eb85a70` · Converged in 7 rounds**

Claude is interrupted twice (C-1, C-2) before producing any result output. Both cards are preserved as `⏸ interrupted` artifacts with partial reasoning visible. C-3 runs cleanly after resume — same agent, fresh prompt built from clean history, no trace of the interruptions in the output. Shows the mid-stream halt contract: interrupted turns are observable artifacts for the user, never inputs to the dialogue.

*Note: shares the same session (`sess_6eb85a70`) as `directive-injection/`. Different framing, same JSONL.*

---

## Session cross-reference

| Session | Used in |
|---------|---------|
| `sess_30285e2d` | `critique-loop/` |
| `sess_89ecd22a` | `convergence/` |
| `sess_6eb85a70` | `directive-injection/` · `mid-stream-halt/` |
| `sess_69a312af` | `round-limit/` |
