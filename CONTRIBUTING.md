# Contributing to koll♠b

koll♠b is a demo and observability project — the goal is legibility, simplicity, and demoability. Contributions that serve those goals are welcome. Contributions that add complexity without a clear payoff in those dimensions probably aren't a fit.

## Before opening a PR

- Check open issues first — if there's an existing issue for what you're working on, comment there before starting.
- For anything non-trivial, open an issue to discuss the approach before writing code. This saves both of us time.
- The project has intentional scope limits — see "What koll♠b is not" in the README. Features outside that scope will be declined.

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

## Commit style

Plain imperative present tense. `fix(ace): handle clean halt during fan-out`, `feat(app): add collapse-all to turn cards`. Scope is the module name when it fits.

## License

By contributing, you agree your contributions are licensed under the Apache 2.0 license that covers this project.
