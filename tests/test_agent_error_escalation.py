import pytest

from kollab import runtime_logging as rl
from kollab.ace import Session, SessionOverrides
from kollab.agents.base import AgentChunk
from kollab.config import Config


class _FakeAgent:
    def __init__(self, error=None, text="hello <verdict>AGREE</verdict>"):
        self.role = "producer"
        self._session_id = "fake-thread"
        self._error = error
        self._text = text

    async def start(self, system_prompt, goal):
        pass

    async def send(self, message, images=None):
        yield AgentChunk(kind="text", content=self._text)
        yield AgentChunk(
            kind="done", content=self._text,
            metadata={"tokens_in": 1, "tokens_out": 1, "error": self._error, "session_id": self._session_id},
        )

    async def stop(self):
        pass

    async def interrupt(self):
        pass


@pytest.mark.asyncio
async def test_agent_error_escalates_logging_and_broadcasts_once(tmp_path) -> None:
    rl.reset_escalation()
    cfg = Config(round_limit=1, sessions_dir=str(tmp_path))
    broadcasts = []
    sess = Session(cfg, broadcasts.append, SessionOverrides(), session_number=1)
    sess._claude = _FakeAgent()
    sess._codex = _FakeAgent(error="The model is not supported.", text="")

    await sess.start("fibonacci algorithm")
    while sess.state in ("claude_turn", "codex_turn"):
        await sess.run_turn()

    assert rl._escalated is True
    error_banners = [b for b in broadcasts if b.get("type") == "error"]
    assert len(error_banners) == 1
    assert "debug logging has been enabled" in error_banners[0]["message"]

    codex_turn = next(t for t in sess.turns if t.actor == "codex")
    assert "agent error: The model is not supported." in codex_turn.anomaly


@pytest.mark.asyncio
async def test_clean_turns_never_escalate(tmp_path) -> None:
    rl.reset_escalation()
    cfg = Config(round_limit=1, sessions_dir=str(tmp_path))
    broadcasts = []
    sess = Session(cfg, broadcasts.append, SessionOverrides(), session_number=1)
    sess._claude = _FakeAgent()
    sess._codex = _FakeAgent()

    await sess.start("fibonacci algorithm")
    while sess.state in ("claude_turn", "codex_turn"):
        await sess.run_turn()

    assert rl._escalated is False
    assert not [b for b in broadcasts if b.get("type") == "error"]
