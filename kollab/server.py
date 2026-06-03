from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import (
    Config, ProviderConfig, ProviderModel,
    load_config, save_config, validate_config, next_session_number,
    provider_is_ready,
)
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
    global _file_handler
    logger = _kollab_logger

    if _file_handler is not None:
        logger.removeHandler(_file_handler)
        _file_handler.close()
        _file_handler = None

    if not cfg.logging_enabled:
        logger.setLevel(logging.WARNING)
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


_apply_logging(_cfg)


# ------------------------------------------------------------------ auth

async def require_api_key(authorization: str | None = Header(default=None)) -> None:
    if not _cfg.api_key:
        return
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
        # providers are managed via /api/providers — exclude from this merge
        body_data = body.model_dump(exclude_unset=True)
        body_data.pop("providers", None)
        updated = Config(**{**_cfg.model_dump(), **body_data})
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)]}
    errors = validate_config(updated)
    if errors:
        return {"ok": False, "errors": errors}
    save_config(updated)
    _cfg = updated
    _apply_logging(_cfg)
    return {"ok": True}


# ------------------------------------------------------------------ providers

def _provider_dict(p: ProviderConfig) -> dict:
    ready, msg = provider_is_ready(p)
    d = p.model_dump()
    d["is_ready"] = ready
    d["ready_message"] = msg
    return d


@app.get("/api/providers", dependencies=[Depends(require_api_key)])
async def list_providers() -> list[dict]:
    return [_provider_dict(p) for p in _cfg.providers]


class ProviderPatch(BaseModel):
    model_config = {"extra": "ignore"}
    name: str | None = None
    binary: str | None = None
    workdir: str | None = None
    api_key_env: str | None = None
    api_base_url: str | None = None
    mcp_enabled: bool | None = None
    enabled: bool | None = None
    models: list[dict] | None = None  # list of {alias, model_id}


class NewProviderBody(BaseModel):
    id: str
    name: str
    type: str
    binary: str = ""
    auth_method: str = "env_var"
    api_key_env: str = ""
    api_base_url: str = ""
    mcp_enabled: bool = False
    workdir: str = ""
    enabled: bool = True
    models: list[dict] = []


@app.post("/api/providers", dependencies=[Depends(require_api_key)])
async def add_provider(body: NewProviderBody) -> dict:
    global _cfg
    if any(p.id == body.id for p in _cfg.providers):
        return {"ok": False, "errors": [f"Provider '{body.id}' already exists"]}
    try:
        models = [ProviderModel(**m) for m in body.models]
        new_p = ProviderConfig(
            id=body.id, name=body.name, type=body.type,  # type: ignore[arg-type]
            binary=body.binary, auth_method=body.auth_method,  # type: ignore[arg-type]
            api_key_env=body.api_key_env, api_base_url=body.api_base_url,
            mcp_enabled=body.mcp_enabled, workdir=body.workdir,
            enabled=body.enabled, models=models,
        )
    except Exception as exc:
        return {"ok": False, "errors": [str(exc)]}
    _cfg.providers.append(new_p)
    save_config(_cfg)
    return {"ok": True, "provider": _provider_dict(new_p)}


@app.patch("/api/providers/{provider_id}", dependencies=[Depends(require_api_key)])
async def patch_provider(provider_id: str, body: ProviderPatch) -> dict:
    global _cfg
    p = next((x for x in _cfg.providers if x.id == provider_id), None)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    if body.name is not None:
        p.name = body.name
    if body.binary is not None:
        p.binary = body.binary
    if body.workdir is not None:
        p.workdir = body.workdir
    if body.api_key_env is not None:
        p.api_key_env = body.api_key_env
    if body.api_base_url is not None:
        p.api_base_url = body.api_base_url
    if body.mcp_enabled is not None:
        p.mcp_enabled = body.mcp_enabled
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.models is not None:
        try:
            p.models = [ProviderModel(**m) for m in body.models]
        except Exception as exc:
            return {"ok": False, "errors": [str(exc)]}
    save_config(_cfg)
    return {"ok": True, "provider": _provider_dict(p)}


@app.delete("/api/providers/{provider_id}", dependencies=[Depends(require_api_key)])
async def delete_provider(provider_id: str) -> dict:
    global _cfg
    before = len(_cfg.providers)
    _cfg.providers = [p for p in _cfg.providers if p.id != provider_id]
    if len(_cfg.providers) == before:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")
    save_config(_cfg)
    return {"ok": True}


@app.post("/api/providers/{provider_id}/validate", dependencies=[Depends(require_api_key)])
async def validate_provider(provider_id: str) -> dict:
    p = next((x for x in _cfg.providers if x.id == provider_id), None)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_id}' not found")

    if p.type in ("claude_sdk", "codex_cli"):
        binary = shutil.which(p.binary) or p.binary
        if not binary:
            return {"ok": False, "message": f"binary '{p.binary}' not found in PATH"}
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            out = (result.stdout or result.stderr or "").strip()
            if result.returncode == 0:
                return {"ok": True, "message": out or "OK"}
            return {"ok": False, "message": out or f"exited {result.returncode}"}
        except FileNotFoundError:
            return {"ok": False, "message": f"binary '{p.binary}' not found"}
        except subprocess.TimeoutExpired:
            return {"ok": False, "message": "timed out after 10s"}

    if p.type == "openai_api":
        import os
        api_key = os.environ.get(p.api_key_env, "")
        if not api_key:
            return {"ok": False, "message": f"{p.api_key_env} not set in environment"}
        try:
            import openai
            client = openai.AsyncOpenAI(
                api_key=api_key,
                base_url=p.api_base_url or None,
            )
            model = p.models[0].model_id if p.models else "gpt-4o-mini"
            await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1,
            )
            return {"ok": True, "message": f"{p.api_key_env} validated"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:200]}

    if p.type == "google_api":
        import os
        api_key = os.environ.get(p.api_key_env, "")
        if not api_key:
            return {"ok": False, "message": f"{p.api_key_env} not set in environment"}
        try:
            from google import genai
            from google.genai import types as genai_types
            client = genai.Client(api_key=api_key)
            model = p.models[0].model_id if p.models else "gemini-1.5-flash"
            await client.aio.models.generate_content(
                model=model,
                contents="hi",
                config=genai_types.GenerateContentConfig(max_output_tokens=1),
            )
            return {"ok": True, "message": f"{p.api_key_env} validated"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)[:200]}

    return {"ok": False, "message": "unknown provider type"}


# ------------------------------------------------------------------ session

class StartSessionBody(BaseModel):
    goal: str
    round_limit: int | None = None
    max_tokens_per_turn: int | None = None
    max_tokens_per_session: int | None = None
    producer_provider_id: str | None = None
    producer_model: str | None = None
    critic_provider_id: str | None = None
    critic_model: str | None = None


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
    overrides = SessionOverrides(
        round_limit=body.round_limit,
        max_tokens_per_turn=body.max_tokens_per_turn,
        max_tokens_per_session=body.max_tokens_per_session,
        producer_provider_id=body.producer_provider_id,
        producer_model=body.producer_model,
        critic_provider_id=body.critic_provider_id,
        critic_model=body.critic_model,
    )
    session = Session(_cfg, _broadcast, overrides=overrides,
                      session_number=next_session_number(_cfg))
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


# ------------------------------------------------------------------ WebSocket

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()
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
    return {"ok": True}


@app.get("/api/sessions/{session_id}", dependencies=[Depends(require_api_key)])
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
        raise HTTPException(status_code=500, detail=str(exc))

    md = _render_export_md(events, session_id, session_number)

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
            lines.append(f"# koll♠b Session Export — {num_label}")
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
