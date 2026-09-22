from __future__ import annotations

import asyncio
import json
import logging

log = logging.getLogger("kollab.codex_models")

# Ascending cost order. Not just trusting the API's own list order for this,
# since that's an implementation detail, not a documented contract.
_REASONING_RANK = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]

_FETCH_TIMEOUT_SECS = 15.0


async def fetch_codex_catalog(binary: str) -> list[dict]:
    """Run `codex debug models` and return its raw `models` list.

    Never raises — a missing binary, non-zero exit, timeout, or malformed
    JSON all just log a warning and return []. Callers must treat that as
    "keep whatever was already there", not as a fatal error.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "debug", "models",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_FETCH_TIMEOUT_SECS)
    except Exception as exc:
        log.warning("codex model catalog fetch failed to launch: %s", exc)
        return []

    if proc.returncode != 0:
        log.warning(
            "codex model catalog fetch exited %s: %s",
            proc.returncode, stderr.decode("utf-8", errors="replace").strip(),
        )
        return []

    try:
        data = json.loads(stdout.decode("utf-8", errors="replace"))
        return data["models"]
    except Exception as exc:
        log.warning("codex model catalog fetch returned unparseable output: %s", exc)
        return []


def _cheapest_reasoning(levels: list[dict]) -> str:
    efforts = {lvl.get("effort") for lvl in levels if lvl.get("effort")}
    for tier in _REASONING_RANK:
        if tier in efforts:
            return tier
    return ""


def build_catalog(raw_models: list[dict]) -> list[dict]:
    """Filter to user-facing models and reduce each to what kollab needs to
    drive the dropdown and the `-m` / `-c model_reasoning_effort` flags."""
    visible = [m for m in raw_models if m.get("visibility") == "list"]
    visible.sort(key=lambda m: m.get("priority", 0))
    return [
        {
            "slug": m["slug"],
            "display_name": m.get("display_name", m["slug"]),
            "reasoning_effort": _cheapest_reasoning(m.get("supported_reasoning_levels", [])),
        }
        for m in visible
        if m.get("slug")
    ]
