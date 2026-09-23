from __future__ import annotations

import logging

# Process-wide, not per-session: an agent error is worth capturing in full
# detail regardless of which session tripped it, and this is a demo tool
# with one server process. Reset whenever the user explicitly changes
# logging config (see server.py's _apply_logging), so an intentional choice
# always wins over a stale escalation.
_escalated = False


def escalate_to_debug() -> bool:
    """Bump the shared 'kollab' logger and its handlers to DEBUG the first
    time an agent error is seen this process, so full detail is captured in
    kollab.log even if the user never enabled verbose logging.

    Returns True only the first time it actually flips, so callers can
    broadcast a one-time UI notice instead of one per error.
    """
    global _escalated
    if _escalated:
        return False
    logger = logging.getLogger("kollab")
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers:
        handler.setLevel(logging.DEBUG)
    _escalated = True
    return True


def reset_escalation() -> None:
    """Called whenever logging config is (re)applied from user settings, so
    an explicit reconfiguration isn't silently overridden by a prior
    auto-escalation."""
    global _escalated
    _escalated = False
