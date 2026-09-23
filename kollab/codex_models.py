from __future__ import annotations

import asyncio
import json
import logging
import re

log = logging.getLogger("kollab.codex_models")

# Ascending cost order. Not just trusting the API's own list order for this,
# since that's an implementation detail, not a documented contract.
_REASONING_RANK = ["minimal", "low", "medium", "high", "xhigh", "max", "ultra"]

# The catalog can carry more than one generation of the same marketing tier
# at once (e.g. both gpt-6-luna and gpt-5.6-luna visible during a rollout) —
# collapse to the most current (lowest priority number) per tier so "Luna"
# doesn't show up twice in the dropdown. Slugs with no recognized tier suffix
# (e.g. "gpt-5.5") pass through untouched.
_TIER_RE = re.compile(r"-(astra|sol|terra|luna)$")

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
    """Filter to user-facing models, dedupe by tier (keep the most current
    generation per astra/sol/terra/luna), and reduce each to what kollab
    needs to drive the dropdown and the `-m` / `-c model_reasoning_effort`
    flags."""
    visible = [m for m in raw_models if m.get("visibility") == "list" and m.get("slug")]
    visible.sort(key=lambda m: m.get("priority", 0))

    seen_tiers: set[str] = set()
    catalog: list[dict] = []
    for m in visible:
        slug = m["slug"]
        tier_match = _TIER_RE.search(slug)
        if tier_match:
            tier = tier_match.group(1)
            if tier in seen_tiers:
                continue  # a more current generation of this tier already kept
            seen_tiers.add(tier)
        catalog.append({
            "slug": slug,
            "display_name": m.get("display_name", slug),
            "reasoning_effort": _cheapest_reasoning(m.get("supported_reasoning_levels", [])),
        })
    return catalog
