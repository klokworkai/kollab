from kollab.ace import _parse_verdict


def test_agree() -> None:
    assert _parse_verdict("some text <verdict>AGREE</verdict>") == "AGREE"


def test_disagree() -> None:
    assert _parse_verdict("<verdict>DISAGREE</verdict>") == "DISAGREE"


def test_revised() -> None:
    assert _parse_verdict("here <verdict>  REVISED  </verdict> end") == "REVISED"


def test_case_insensitive() -> None:
    assert _parse_verdict("<verdict>agree</verdict>") == "AGREE"


def test_absent() -> None:
    assert _parse_verdict("no verdict here") is None


def test_absent_empty() -> None:
    assert _parse_verdict("") is None
