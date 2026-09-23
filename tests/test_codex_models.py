from kollab.codex_models import build_catalog


def _model(slug, priority, visibility="list", levels=("low", "medium", "high")):
    return {
        "slug": slug,
        "display_name": slug.upper(),
        "visibility": visibility,
        "priority": priority,
        "supported_reasoning_levels": [{"effort": e} for e in levels],
    }


def test_build_catalog_filters_hidden_models() -> None:
    raw = [_model("gpt-6-luna", 3), _model("codex-auto-review", 43, visibility="hide")]
    catalog = build_catalog(raw)
    assert [m["slug"] for m in catalog] == ["gpt-6-luna"]


def test_build_catalog_sorts_by_priority_ascending() -> None:
    raw = [_model("gpt-5.5", 12), _model("gpt-6-luna", 3), _model("gpt-5.6-terra", 7)]
    catalog = build_catalog(raw)
    assert [m["slug"] for m in catalog] == ["gpt-6-luna", "gpt-5.6-terra", "gpt-5.5"]


def test_build_catalog_picks_cheapest_reasoning_effort() -> None:
    raw = [_model("gpt-6-luna", 3, levels=("high", "medium", "xhigh", "low"))]
    catalog = build_catalog(raw)
    assert catalog[0]["reasoning_effort"] == "low"


def test_build_catalog_handles_missing_reasoning_levels() -> None:
    raw = [_model("gpt-6-luna", 3, levels=())]
    catalog = build_catalog(raw)
    assert catalog[0]["reasoning_effort"] == ""


def test_build_catalog_skips_entries_without_slug() -> None:
    raw = [_model("gpt-6-luna", 3), {"visibility": "list", "priority": 1}]
    catalog = build_catalog(raw)
    assert [m["slug"] for m in catalog] == ["gpt-6-luna"]


def test_build_catalog_keeps_multiple_generations_of_same_tier() -> None:
    """Codex's own `/model` picker lists gpt-6-luna and gpt-5.6-luna as two
    distinct, separately-selectable models (confirmed via screenshot) — not
    a duplicate to collapse."""
    raw = [_model("gpt-5.6-luna", 8), _model("gpt-6-luna", 3), _model("gpt-5.6-terra", 7)]
    catalog = build_catalog(raw)
    assert [m["slug"] for m in catalog] == ["gpt-6-luna", "gpt-5.6-terra", "gpt-5.6-luna"]
