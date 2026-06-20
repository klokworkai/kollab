from kollab.ace import _detect_anomaly


def test_normal_turn_has_no_anomaly() -> None:
    assert _detect_anomaly("solid critique text", "REVISED", is_first_turn=False) is None


def test_first_turn_without_verdict_is_not_anomalous() -> None:
    assert _detect_anomaly("initial proposal", None, is_first_turn=True) is None


def test_first_turn_with_empty_text_is_anomalous() -> None:
    anomaly = _detect_anomaly("", None, is_first_turn=True)
    assert anomaly == "empty response text"


def test_later_turn_missing_verdict_is_anomalous() -> None:
    anomaly = _detect_anomaly("some text but no trailer", None, is_first_turn=False)
    assert anomaly == "no verdict trailer"


def test_later_turn_empty_and_missing_verdict_reports_both() -> None:
    anomaly = _detect_anomaly("", None, is_first_turn=False)
    assert anomaly == "empty response text, no verdict trailer"


def test_whitespace_only_text_counts_as_empty() -> None:
    anomaly = _detect_anomaly("   \n  ", "AGREE", is_first_turn=False)
    assert anomaly == "empty response text"
