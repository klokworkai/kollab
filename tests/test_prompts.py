from kollab.prompts import (
    FIRST_TURN_RESUME_PREFIX,
    RESUME_PREFIX,
    build_first_turn_prompt,
    build_turn_prompt,
    compose_system_prompt,
)


def test_turn_prompt_no_resume_prefix() -> None:
    p = build_turn_prompt(2, "Codex", "some peer output")
    assert RESUME_PREFIX not in p
    assert "Codex" in p
    assert "some peer output" in p


def test_turn_prompt_with_resume_prefix() -> None:
    p = build_turn_prompt(2, "Codex", "peer", resume_after_halt=True)
    assert p.startswith(RESUME_PREFIX)



def test_first_turn_prompt_basic() -> None:
    p = build_first_turn_prompt("solve world hunger")
    assert "solve world hunger" in p
    assert "[Round 1]" in p
    assert FIRST_TURN_RESUME_PREFIX not in p


def test_first_turn_prompt_with_resume_prefix() -> None:
    p = build_first_turn_prompt("solve world hunger", resume_after_halt=True)
    assert p.startswith(FIRST_TURN_RESUME_PREFIX)
    assert "solve world hunger" in p


def test_compose_system_prompt_includes_user_profile_section() -> None:
    p = compose_system_prompt("base prompt", "", False, "Senior backend engineer")
    assert "## User Profile\nSenior backend engineer" in p
    assert "## Instructions\nbase prompt" in p


def test_compose_system_prompt_empty_profile_uses_fallback() -> None:
    p = compose_system_prompt("base prompt", "", False, "")
    assert "## User Profile\nNo user profile provided." in p


def test_compose_system_prompt_profile_independent_of_disabled() -> None:
    p = compose_system_prompt("base prompt", "", True, "Loves Rust")
    assert "## User Profile\nLoves Rust" in p
    assert "## Instructions" not in p


