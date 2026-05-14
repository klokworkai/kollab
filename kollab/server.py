from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config, save_config, validate_config, next_session_number
from .ace import Session, SessionOverrides

app = FastAPI(title="kollab")

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# --- global state (single session at a time) ---
_cfg: Config = load_config()
_session: Session | None = None
_ws_clients: list[WebSocket] = []
_session_task: asyncio.Task | None = None

_LOG_PATH = Path("~/.kollab/kollab.log").expanduser()
_file_handler: logging.FileHandler | None = None
_kollab_logger = logging.getLogger("kollab")


def _apply_logging(cfg: Config) -> None:
    """Configure or tear down file logging based on current config."""
    global _file_handler
    logger = _kollab_logger

    # Remove existing file handler first
    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None

    if not cfg.logging_enabled:
        logger.setLevel(logging.WARNING)  # effectively silent
        return

    level = logging.DEBUG if cfg.logging_level == "debug" else logging.INFO
    logger.setLevel(level)

    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_PATH, encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    logger.addHandler(handler)
    _file_handler = handler
    logger.info("Logging started (level=%s, file=%s)", cfg.logging_level, _LOG_PATH)


# Apply logging on startup from loaded config
_apply_logging(_cfg)


# ------------------------------------------------------------------ broadcast

def _broadcast(msg: dict) -> None:
    data = json.dumps(msg)
    dead: list[WebSocket] = []
    for ws in _ws_clients:
        try:
            asyncio.ensure_future(ws.send_text(data))
        except Exception:
            dead.append(ws)
    for ws in dead:
        _ws_clients.remove(ws)


# ------------------------------------------------------------------ static

@app.get("/about")
async def about() -> FileResponse:
    return FileResponse(_static_dir / "about.html")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_static_dir / "index.html")


# ------------------------------------------------------------------ config

@app.get("/api/config")
async def get_config() -> dict:
    return _cfg.model_dump()


class ConfigUpdate(BaseModel):
    model_config = {"extra": "allow"}


@app.post("/api/config")
async def post_config(body: ConfigUpdate) -> dict:
    global _cfg
    try:
        updated = Config(**{**_cfg.model_dump(), **body.model_dump(exclude_unset=True)})
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)]}
    errors = validate_config(updated)
    if errors:
        return {"ok": False, "errors": errors}
    save_config(updated)
    _cfg = updated
    _apply_logging(_cfg)
    return {"ok": True}


# ------------------------------------------------------------------ session

class StartSessionBody(BaseModel):
    goal: str
    round_limit: int | None = None
    max_tokens_per_turn: int | None = None
    max_tokens_per_session: int | None = None
    claude_model: str | None = None
    codex_model: str | None = None


class UserInputBody(BaseModel):
    text: str
    target: str = "both"


@app.post("/api/session")
async def start_session(body: StartSessionBody) -> dict:
    global _session, _session_task
    if _session is not None and _session.state not in ("done", "halted"):
        raise HTTPException(status_code=409, detail="A session is already active.")
    overrides = SessionOverrides(
        round_limit=body.round_limit,
        max_tokens_per_turn=body.max_tokens_per_turn,
        max_tokens_per_session=body.max_tokens_per_session,
        claude_model=body.claude_model,
        codex_model=body.codex_model,
    )
    _session = Session(_cfg, _broadcast, overrides=overrides,
                        session_number=next_session_number(_cfg))
    _session_task = asyncio.create_task(_run_session(body.goal))
    return {"session_id": _session.id, "session_number": _session.session_number}


@app.post("/api/session/stop")
async def stop_session() -> dict:
    if _session is None:
        raise HTTPException(status_code=404, detail="No active session.")
    _session.stop()
    return {"ok": True}


@app.post("/api/session/resume")
async def resume_session() -> dict:
    global _session_task
    if _session is None:
        raise HTTPException(status_code=404, detail="No session.")
    await _session.resume()
    _session_task = asyncio.create_task(_resume_loop())
    return {"ok": True}


@app.post("/api/session/input")
async def session_input(body: UserInputBody) -> dict:
    if _session is None:
        raise HTTPException(status_code=404, detail="No active session.")
    await _session.handle_user_input(body.text, body.target)
    return {"ok": True}


# ------------------------------------------------------------------ WebSocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # keep connection alive; client sends nothing
    except WebSocketDisconnect:
        pass
    finally:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


# ------------------------------------------------------------------ session runner

async def _run_session(goal: str) -> None:
    assert _session is not None
    try:
        await _session.start(goal)
        while _session.state in ("claude_turn", "codex_turn"):
            await _session.run_turn()
    except Exception as exc:
        _broadcast({"type": "error", "message": str(exc)})
    finally:
        if _session.state != "halted":
            await _session.close()


async def _resume_loop() -> None:
    assert _session is not None
    try:
        while _session.state in ("claude_turn", "codex_turn"):
            await _session.run_turn()
    except Exception as exc:
        _broadcast({"type": "error", "message": str(exc)})
    finally:
        if _session.state != "halted":
            await _session.close()


@app.post("/api/shutdown")
async def shutdown() -> dict:
    import signal
    import os
    if _session is not None:
        if _session.state not in ("done", "halted"):
            _session.stop()
        await _session.close()
    asyncio.get_event_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"ok": True}


# ------------------------------------------------------------------ session history

@app.get("/api/sessions")
async def list_sessions() -> list[dict]:
    sessions_dir = Path(_cfg.sessions_dir)
    results: list[dict] = []
    for path in sessions_dir.glob("*.jsonl"):
        try:
            events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        except Exception:
            print(f"Warning: could not parse {path}", file=sys.stderr)
            continue
        entry: dict[str, Any] = {}
        for ev in events:
            kind = ev.get("kind")
            if kind == "session_start":
                entry["session_id"] = ev.get("session_id", path.stem)
                entry["goal"] = ev.get("payload", {}).get("goal", "")
                entry["started_at"] = ev.get("ts", "")
                entry["session_number"] = ev.get("payload", {}).get("session_number", 0)
            elif kind == "session_end":
                entry["end_reason"] = ev.get("payload", {}).get("reason", "")
                entry["round_count"] = ev.get("round", 0)
        if "session_id" in entry:
            results.append(entry)
    results.sort(key=lambda x: x.get("started_at", ""), reverse=True)
    # Retroactively assign session numbers to legacy sessions (session_number == 0).
    # Sort oldest-first, assign 1..N only to those missing a number.
    unumbered = [r for r in results if not r.get("session_number")]
    unumbered.sort(key=lambda x: x.get("started_at", ""))
    for i, r in enumerate(unumbered, start=1):
        r["session_number"] = i
    return results


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict:
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    path.unlink()
    return {"ok": True}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict:
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return {"session_id": session_id, "events": events}


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str, session_number: int = 0) -> Any:
    from fastapi.responses import Response
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    md = _render_export_md(events, session_id, session_number)

    # Derive filename: prefer JSONL payload, fall back to query param
    sn = 0
    started_at = ""
    for ev in events:
        if ev.get("kind") == "session_start":
            sn = ev.get("payload", {}).get("session_number", 0) or session_number
            started_at = ev.get("ts", "")[:10]
            break
    if not sn:
        sn = session_number
    num_str = str(sn).zfill(3) if sn else "000"
    date_str = started_at or "unknown"
    filename = f"kollab-{num_str}-{date_str}.md"

    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _render_export_md(events: list[dict], session_id: str, fallback_session_number: int = 0) -> str:
    """Render a full-fidelity markdown transcript from a session's JSONL events."""
    lines: list[str] = []

    goal = ""
    session_number = 0
    started_at = ""

    for ev in events:
        kind = ev.get("kind", "")
        ts = ev.get("ts", "")
        ts_short = ts[:19].replace("T", " ") if ts else ""

        if kind == "session_start":
            goal = ev.get("payload", {}).get("goal", "")
            session_number = ev.get("payload", {}).get("session_number", 0) or fallback_session_number
            started_at = ts_short
            num_label = f"#{session_number}" if session_number else session_id
            lines.append(f"# koll\u2660b Session Export — {num_label}")
            lines.append("")
            lines.append(f"**Session:** {num_label}  ")
            lines.append(f"**Started:** {started_at}  ")
            lines.append(f"**Session ID:** `{session_id}`  ")
            lines.append("")
            lines.append("## Goal")
            lines.append("")
            lines.append(goal)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif kind == "turn_start":
            actor = ev.get("actor", "")
            role = ev.get("role", "")
            turn_id = ev.get("turn_id", "")
            round_n = ev.get("round", 0)
            actor_label = "Claude" if actor == "claude" else "Codex"
            lines.append(f"## {turn_id} — {actor_label} ({role})")
            lines.append("")
            lines.append(f"*Round {round_n} · {ts_short}*")
            lines.append("")

        elif kind == "turn_end":
            payload = ev.get("payload", {})
            turn_id = ev.get("turn_id", "")
            verdict = payload.get("verdict") or ""
            thread_id = payload.get("thread_id") or ""
            duration_ms = payload.get("duration_ms") or 0
            reasoning = payload.get("reasoning") or ""
            text = payload.get("text") or ""

            if reasoning:
                lines.append("<details>")
                lines.append("<summary>Reasoning</summary>")
                lines.append("")
                lines.append(reasoning)
                lines.append("")
                lines.append("</details>")
                lines.append("")

            lines.append(text)
            lines.append("")

            meta_parts = []
            if verdict:
                meta_parts.append(f"**Verdict:** {verdict}")
            if thread_id:
                meta_parts.append(f"**Thread:** `{thread_id}`")
            if duration_ms:
                meta_parts.append(f"**Duration:** {duration_ms}ms")
            if meta_parts:
                lines.append(" · ".join(meta_parts))
                lines.append("")
            lines.append("---")
            lines.append("")

        elif kind == "turn_interrupted":
            payload = ev.get("payload", {})
            turn_id = ev.get("turn_id", "")
            thread_id = payload.get("thread_id") or ""
            reasoning = payload.get("reasoning") or ""
            text = payload.get("text") or ""

            lines.append("> ⏸ **INTERRUPTED** — partial output below. This turn was not fed back to any agent.")
            lines.append("")

            if reasoning:
                lines.append("<details>")
                lines.append("<summary>Reasoning (partial)</summary>")
                lines.append("")
                lines.append(reasoning)
                lines.append("")
                lines.append("</details>")
                lines.append("")

            if text:
                lines.append(text)
                lines.append("")
            else:
                lines.append("*(no output before interrupt)*")
                lines.append("")

            if thread_id:
                lines.append(f"**Thread:** `{thread_id}`")
                lines.append("")
            lines.append("---")
            lines.append("")

        elif kind == "user_input":
            payload = ev.get("payload", {})
            target = payload.get("target", "both")
            text = payload.get("text") or ""
            target_labels = {"claude": "CLAUDE", "codex": "CODEX", "both": "CLAUDE, CODEX"}
            target_label = target_labels.get(target, target.upper())
            lines.append(f"**DIRECTIVE → {target_label}** ·  *{ts_short}*")
            lines.append("")
            lines.append(text)
            lines.append("")
            lines.append("---")
            lines.append("")

        elif kind == "session_end":
            reason = ev.get("payload", {}).get("reason", "")
            round_n = ev.get("round", 0)
            reason_labels = {
                "convergence": "✓ Both agents reached agreement",
                "round_limit": "⚠ Round limit reached",
                "token_limit": "⚠ Token budget exhausted",
                "halted": "⏹ Session halted by user",
                "expired": "⏳ Session auto-expired",
            }
            lines.append("## Session End")
            lines.append("")
            lines.append(f"**Reason:** {reason_labels.get(reason, reason)}  ")
            lines.append(f"**Final round:** {round_n}  ")
            lines.append(f"**Ended:** {ts_short}  ")
            lines.append("")

    return "\n".join(lines)
