from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .attachments import (
    AttachmentMeta,
    adopt_staged_attachments,
    cleanup_stale_staging,
    create_upload_id,
    delete_staged_file,
    delete_staging_dir,
    get_staged_count,
    get_staged_total_bytes,
    guess_mime,
    is_allowed_mime,
    stage_file,
)
from .config import Config, MODEL_ALIASES, load_config, save_config, validate_config, next_session_number
from .ace import Session, SessionOverrides

app = FastAPI(title="kollab")

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# --- global state ---
_cfg: Config = load_config()
_sessions: dict[str, Session] = {}
_session_tasks: dict[str, asyncio.Task] = {}
_ws_clients: list[WebSocket] = []

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

# Clean up stale staging dirs from previous runs
cleanup_stale_staging()


# ------------------------------------------------------------------ auth

async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    if not _cfg.api_key:
        return  # auth disabled — local browser use unaffected
    if authorization != f"Bearer {_cfg.api_key}":
        raise HTTPException(status_code=401, detail="Unauthorized")


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

@app.get("/api/config", dependencies=[Depends(require_api_key)])
async def get_config() -> dict:
    return _cfg.model_dump()


class ConfigUpdate(BaseModel):
    model_config = {"extra": "allow"}


@app.post("/api/config", dependencies=[Depends(require_api_key)])
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
    staging_id: str | None = None


class UserInputBody(BaseModel):
    text: str
    target: str = "both"


@app.get("/api/session", dependencies=[Depends(require_api_key)])
async def get_session_state(session_id: str | None = None) -> dict:
    session = _sessions.get(session_id) if session_id else (list(_sessions.values())[-1] if _sessions else None)
    if session is None:
        return {"session_id": None, "state": "idle"}
    started_at = None
    if session.turns:
        ts = session.turns[0].started_at
        started_at = ts.isoformat().replace("+00:00", "Z")
    return {
        "session_id": session.id,
        "session_number": session.session_number,
        "state": session.state,
        "round": session.round,
        "goal": session.goal,
        "turns_completed": sum(1 for t in session.turns if not t.interrupted),
        "started_at": started_at,
    }


@app.post("/api/session", dependencies=[Depends(require_api_key)])
async def start_session(body: StartSessionBody) -> dict:
    def _resolve(model: str | None) -> str | None:
        if model is None:
            return None
        return MODEL_ALIASES.get(model, model)

    # Adopt any staged attachments before constructing the session so the
    # session ID is known and the files land in the right directory.
    attachments: list[AttachmentMeta] = []
    if body.staging_id:
        sessions_dir = Path(_cfg.sessions_dir).expanduser()
        session_id_override = f"sess_{uuid.uuid4().hex[:8]}"
        try:
            attachments = adopt_staged_attachments(body.staging_id, session_id_override, sessions_dir)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid staging_id: {exc}")
    else:
        session_id_override = None

    overrides = SessionOverrides(
        round_limit=body.round_limit,
        max_tokens_per_turn=body.max_tokens_per_turn,
        max_tokens_per_session=body.max_tokens_per_session,
        claude_model=_resolve(body.claude_model),
        codex_model=_resolve(body.codex_model),
        attachments=attachments,
    )
    session = Session(_cfg, _broadcast, overrides=overrides,
                      session_number=next_session_number(_cfg),
                      session_id=session_id_override)
    _sessions[session.id] = session
    _session_tasks[session.id] = asyncio.create_task(_run_session(session.id, body.goal))
    return {
        "session_id": session.id,
        "session_number": session.session_number,
        "state": "fanning_out",
    }


@app.post("/api/session/stop", dependencies=[Depends(require_api_key)])
async def stop_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No session with that ID.")
    session.stop()
    return {"ok": True}


@app.post("/api/session/resume", dependencies=[Depends(require_api_key)])
async def resume_session(session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No session with that ID.")
    await session.resume()
    _session_tasks[session_id] = asyncio.create_task(_resume_loop(session_id))
    return {"ok": True}


@app.post("/api/session/input", dependencies=[Depends(require_api_key)])
async def session_input(body: UserInputBody, session_id: str) -> dict:
    session = _sessions.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="No session with that ID.")
    await session.handle_user_input(body.text, body.target)
    return {"ok": True}


# ------------------------------------------------------------------ attachment staging

_UPLOAD_CHUNK = 64 * 1024  # 64 KB read chunks


@app.post("/api/attachments/stage", dependencies=[Depends(require_api_key)])
async def stage_attachment(
    file: UploadFile = File(...),
    upload_id: str | None = Form(default=None),
) -> dict:
    filename = file.filename or "upload"
    mime_type = file.content_type or guess_mime(filename)

    if not is_allowed_mime(mime_type):
        return {"ok": False, "error": f"{filename} is not a supported file type."}

    uid = upload_id or create_upload_id()
    max_file_bytes  = _cfg.attachment_max_file_kb  * 1024
    max_total_bytes = _cfg.attachment_max_total_kb * 1024

    # File-count quota — check before reading to avoid buffering a rejected file.
    if get_staged_count(uid) >= _cfg.attachment_max_files:
        return {"ok": False, "error": f"Maximum {_cfg.attachment_max_files} files per session."}

    # Per-file size: stream in chunks to avoid buffering the whole file first.
    chunks: list[bytes] = []
    received = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        received += len(chunk)
        if received > max_file_bytes:
            return {"ok": False, "error": f"File exceeds {_cfg.attachment_max_file_kb} KB limit."}
        chunks.append(chunk)
    data = b"".join(chunks)

    # Total-payload quota.
    if get_staged_total_bytes(uid) + len(data) > max_total_bytes:
        return {"ok": False, "error": f"Total payload would exceed {_cfg.attachment_max_total_kb} KB limit."}

    meta = stage_file(uid, data, filename, mime_type)
    return {
        "ok": meta.error is None,
        "upload_id": uid,
        "file": meta.to_dict(),
    }


@app.delete("/api/attachments/stage/{upload_id}", dependencies=[Depends(require_api_key)])
async def delete_staging(upload_id: str) -> dict:
    delete_staging_dir(upload_id)
    return {"ok": True}


@app.delete("/api/attachments/stage/{upload_id}/{filename}", dependencies=[Depends(require_api_key)])
async def delete_staged_attachment(upload_id: str, filename: str) -> dict:
    delete_staged_file(upload_id, filename)
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

async def _run_session(session_id: str, goal: str) -> None:
    session = _sessions.get(session_id)
    if session is None:
        return
    try:
        await session.start(goal)
        while session.state in ("claude_turn", "codex_turn"):
            await session.run_turn()
    except Exception as exc:
        _broadcast({"type": "error", "message": str(exc)})
    finally:
        if session.state != "halted":
            await session.close()
            _sessions.pop(session_id, None)
            _session_tasks.pop(session_id, None)


async def _resume_loop(session_id: str) -> None:
    session = _sessions.get(session_id)
    if session is None:
        return
    try:
        while session.state in ("claude_turn", "codex_turn"):
            await session.run_turn()
    except Exception as exc:
        _broadcast({"type": "error", "message": str(exc)})
    finally:
        if session.state != "halted":
            await session.close()
            _sessions.pop(session_id, None)
            _session_tasks.pop(session_id, None)


@app.post("/api/shutdown", dependencies=[Depends(require_api_key)])
async def shutdown() -> dict:
    import signal
    import os
    for session in list(_sessions.values()):
        if session.state not in ("done", "halted"):
            session.stop()
        await session.close()
    _sessions.clear()
    _session_tasks.clear()
    asyncio.get_event_loop().call_later(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
    return {"ok": True}


# ------------------------------------------------------------------ session history

@app.get("/api/sessions", dependencies=[Depends(require_api_key)])
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


@app.delete("/api/sessions/{session_id}", dependencies=[Depends(require_api_key)])
async def delete_session(session_id: str) -> dict:
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    path.unlink()
    attachments_dir = sessions_dir / session_id / "attachments"
    if attachments_dir.exists():
        shutil.rmtree(attachments_dir, ignore_errors=True)
    session_dir = sessions_dir / session_id
    try:
        session_dir.rmdir()  # only removes if empty
    except OSError:
        pass
    return {"ok": True}


@app.get("/api/sessions/{session_id}/summary", dependencies=[Depends(require_api_key)])
async def get_session_summary(session_id: str) -> dict:
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return _build_arc_summary(events)


def _build_arc_summary(events: list[dict]) -> dict:
    turns: list[dict] = []
    end_reason: str = ""
    for ev in events:
        kind = ev.get("kind")
        if kind == "turn_end":
            summary = ev.get("payload", {}).get("summary") or ""
            if summary:
                turns.append({
                    "turn_id": ev.get("turn_id", ""),
                    "actor": ev.get("actor", ""),
                    "summary": summary,
                })
        elif kind == "session_end":
            end_reason = ev.get("payload", {}).get("reason", "")
    return {"turns": turns, "end_reason": end_reason}


@app.get("/api/sessions/{session_id}", dependencies=[Depends(require_api_key)])
async def get_session(session_id: str) -> dict:
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"session_id": session_id, "events": events}


@app.get("/api/sessions/{session_id}/export", dependencies=[Depends(require_api_key)])
async def export_session(session_id: str, session_number: int = 0) -> Any:
    from fastapi.responses import Response
    sessions_dir = Path(_cfg.sessions_dir)
    path = sessions_dir / f"{session_id}.jsonl"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Session not found.")
    try:
        events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
