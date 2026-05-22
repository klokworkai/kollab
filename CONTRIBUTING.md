# Contributing to koll♠b

koll♠b is a demo and observability project — the goal is legibility, simplicity, and demoability. Contributions that serve those goals are welcome. Contributions that add complexity without a clear payoff in those dimensions probably aren't a fit.

## Before opening a PR

- Check open issues first — if there's an existing issue for what you're working on, comment there before starting.
- For anything non-trivial, open an issue to discuss the approach before writing code. This saves both of us time.
- The project has intentional scope limits. kollab is a single-user local demo tool — not a production orchestration framework, not a multi-agent platform, not a CI/CD system. Features outside that scope will be declined.

## What's in scope

- Bug fixes
- Reliability improvements to the halt/resume/interrupt lifecycle
- Improvements to turn card rendering, streaming fidelity, or export quality
- Better error surfacing in the UI
- Test coverage for `ace.py` state machine logic
- Documentation improvements

## What's out of scope (don't open PRs for these)

- Multi-user, auth, cloud deployment
- Role swap mid-session
- Database-backed session storage
- New agent integrations (beyond Claude + Codex)
- GitHub MCP wiring — parked, not accepting external PRs until the design is settled

## Dev setup

```bash
git clone https://github.com/klokworkai/kollab
cd kollab
pip install -e ".[dev]"
```

Note: `pip install -e .` generates a `kollab.egg-info/` directory and `pytest` generates `.pytest_cache/` — both are in `.gitignore` and should not be committed.

Run tests:

```bash
pytest
```

Run with hot reload:

```bash
uvicorn kollab.server:app --reload --port 8765
```

## Code conventions

- Type hints everywhere. No untyped Python.
- `async`/`await` for all I/O paths.
- No global state beyond the single `Session` object in `server.py`.
- Errors surface in the UI, not silently in logs.
- If a value can be configured, it belongs in `Config`. If it's a constant, it goes at the top of its module.
- Keep components small. Each module does one thing.

## Branch naming

Use the same type prefixes as commit messages:

| Prefix | Use for |
|---|---|
| `feat/` | New features or behaviour |
| `fix/` | Bug fixes |
| `docs/` | Documentation only |
| `test/` | Test additions or fixes |
| `chore/` | Tooling, config, dependencies, repo maintenance |
| `refactor/` | Code restructuring with no behaviour change |

Format: `type/short-description` — lowercase, hyphens, no spaces.

Examples:
- `feat/webhook-configure-modal`
- `fix/mid-stream-halt-codex`
- `docs/update-runbook-auth-steps`
- `chore/coderabbit-config`

One branch per logical change. Keep branches short-lived — open a PR, merge, delete.

## Commit style

This project follows [Conventional Commits](https://www.conventionalcommits.org). Format: `type(scope): description` in plain imperative present tense. Scope is the module name when it fits.

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`. Examples:
- `fix(ace): handle clean halt during fan-out`
- `feat(app): add collapse-all to turn cards`
- `docs(examples): add directive injection screenshot`
- `chore: update .gitignore glob for .DS_Store`

## Project context

koll♠b is developed with Claude Code as a hands-on collaborator. The standing design context — architecture decisions, locked patterns, conventions — lives in the Klokwork AI design repository rather than this repo. It's internal working material, not part of the OSS distribution. Commit messages in early history reference `CLAUDE.md`; that file was the in-repo version of that context before it was moved to the design repo.

## License

By contributing, you agree your contributions are licensed under the Apache 2.0 license that covers this project.
