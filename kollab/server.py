from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config, save_config, validate_config
from .orchestrator import Session

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


class UserInputBody(BaseModel):
    text: str


@app.post("/api/session")
async def start_session(body: StartSessionBody) -> dict:
    global _session, _session_task
    if _session is not None and _session.state not in ("done", "halted"):
        raise HTTPException(status_code=409, detail="A session is already active.")
    _session = Session(_cfg, _broadcast)
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
    await _session.handle_user_input(body.text)
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
        await _session.close()


async def _resume_loop() -> None:
    assert _session is not None
    try:
        while _session.state in ("claude_turn", "codex_turn"):
            await _session.run_turn()
    except Exception as exc:
        _broadcast({"type": "error", "message": str(exc)})
