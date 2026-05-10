from kollab.ace import Session, Turn
from kollab.config import Config


def _make_session() -> Session:
    return Session(Config(), lambda _: None)


def test_turn_id_sequence() -> None:
    s = _make_session()
    ids = []
    for _ in range(3):
        s._claude_turn_count += 1
        ids.append(f"C-{s._claude_turn_count}")
    for _ in range(2):
        s._codex_turn_count += 1
        ids.append(f"X-{s._codex_turn_count}")
    assert ids == ["C-1", "C-2", "C-3", "X-1", "X-2"]


def test_turn_ids_interleaved() -> None:
    s = _make_session()
    result = []
    for i in range(1, 4):
        s._claude_turn_count += 1
        result.append(f"C-{s._claude_turn_count}")
        s._codex_turn_count += 1
        result.append(f"X-{s._codex_turn_count}")
    assert result == ["C-1", "X-1", "C-2", "X-2", "C-3", "X-3"]


def test_last_turn_for_skips_interrupted() -> None:
    """_last_turn_for must ignore interrupted turns so prompt rebuilds use
    only completed peer output, per spec."""
    s = _make_session()
    s.turns.append(Turn(id="C-1", actor="claude", role="producer", round=1,
                        text="clean output"))
    # interrupted Claude turn after — should be invisible
    s.turns.append(Turn(id="C-2", actor="claude", role="producer", round=1,
                        text="partial garbage", interrupted=True))
    last = s._last_turn_for("claude")
    assert last is not None
    assert last.id == "C-1"
    assert last.text == "clean output"


def test_last_turn_for_returns_none_when_only_interrupted() -> None:
    s = _make_session()
    s.turns.append(Turn(id="C-1", actor="claude", role="producer", round=1,
                        text="partial", interrupted=True))
    assert s._last_turn_for("claude") is None
