import re

_REF_RE = re.compile(r"\b([CX]-\d+)\b")


def _parse_refs(text: str) -> list[str]:
    return _REF_RE.findall(text)


def test_single_claude_ref() -> None:
    assert _parse_refs("elaborate on C-3") == ["C-3"]


def test_single_codex_ref() -> None:
    assert _parse_refs("X-2 was wrong about latency") == ["X-2"]


def test_multiple_refs() -> None:
    assert _parse_refs("compare C-1 and X-2 then check C-3") == ["C-1", "X-2", "C-3"]


def test_no_ref() -> None:
    assert _parse_refs("just a plain message") == []


def test_partial_no_match() -> None:
    assert _parse_refs("CC-3 is not a valid ref") == []
