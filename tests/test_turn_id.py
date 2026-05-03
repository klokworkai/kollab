from kollab.ace import Session
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
