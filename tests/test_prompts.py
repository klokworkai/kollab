from kollab.prompts import (
    FIRST_TURN_RESUME_PREFIX,
    RESUME_PREFIX,
    build_first_turn_prompt,
    build_turn_prompt,
)


def test_turn_prompt_no_resume_prefix() -> None:
    p = build_turn_prompt(2, "Codex", "some peer output")
    assert RESUME_PREFIX not in p
    assert "Codex" in p
    assert "some peer output" in p


def test_turn_prompt_with_resume_prefix() -> None:
    p = build_turn_prompt(2, "Codex", "peer", resume_after_halt=True)
    assert p.startswith(RESUME_PREFIX)


def test_turn_prompt_with_directive() -> None:
    p = build_turn_prompt(2, "Codex", "peer", user_injection="focus on security")
    assert "[user]: focus on security" in p


def test_first_turn_prompt_basic() -> None:
    p = build_first_turn_prompt("solve world hunger")
    assert "solve world hunger" in p
    assert "[Round 1]" in p
    assert FIRST_TURN_RESUME_PREFIX not in p


def test_first_turn_prompt_with_resume_prefix() -> None:
    p = build_first_turn_prompt("solve world hunger", resume_after_halt=True)
    assert p.startswith(FIRST_TURN_RESUME_PREFIX)
    assert "solve world hunger" in p


def test_first_turn_prompt_with_directive_and_resume() -> None:
    p = build_first_turn_prompt(
        "solve world hunger",
        user_injection="constraint: no GMOs",
        resume_after_halt=True,
    )
    assert p.startswith(FIRST_TURN_RESUME_PREFIX)
    assert "[user]: constraint: no GMOs" in p
