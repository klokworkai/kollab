from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config, save_config, validate_config
from .ace import Session, SessionOverrides

app = FastAPI(title="kollab")

_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# --- global state (single session at a time) ---
_cfg: Config = load_config()
_session: Session | None = None
_ws_clients: list[WebSocket] = []
_session_task: asyncio.Task | None = None


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
    _session = Session(_cfg, _broadcast, overrides=overrides)
    _session_task = asyncio.create_task(_run_session(body.goal))
    return {"session_id": _session.id}


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
            elif kind == "session_end":
                entry["end_reason"] = ev.get("payload", {}).get("reason", "")
                entry["round_count"] = ev.get("round", 0)
        if "session_id" in entry:
            results.append(entry)
    results.sort(key=lambda x: x.get("started_at", ""), reverse=True)
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
