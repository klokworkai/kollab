import logging

from kollab import runtime_logging as rl


def _reset():
    rl._escalated = False
    logging.getLogger("kollab").setLevel(logging.WARNING)


def test_escalate_to_debug_bumps_level_and_returns_true_once() -> None:
    _reset()
    assert rl.escalate_to_debug() is True
    assert logging.getLogger("kollab").level == logging.DEBUG
    assert rl.escalate_to_debug() is False  # already escalated


def test_reset_escalation_allows_re_escalating() -> None:
    _reset()
    assert rl.escalate_to_debug() is True
    rl.reset_escalation()
    assert rl.escalate_to_debug() is True
