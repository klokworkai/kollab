from kollab.agents.codex_agent import CodexAgent


def _make_agent(**kwargs) -> CodexAgent:
    return CodexAgent(
        role="producer",
        binary="codex",
        model="gpt-5.4",
        workdir="/tmp/workdir",
        **kwargs,
    )


def test_build_cmd_uses_full_auto_not_bypass() -> None:
    agent = _make_agent()
    cmd = agent._build_cmd("hello", new_session=True)
    assert "--full-auto" in cmd
    assert "--dangerously-bypass-approvals-and-sandbox" not in cmd


def test_build_cmd_adds_dir_flags_per_path_when_enabled() -> None:
    agent = _make_agent(mcp_filesystem_enabled=True, mcp_filesystem_paths=["/a", "/b"])
    cmd = agent._build_cmd("hello", new_session=True)
    assert cmd.count("--add-dir") == 2
    assert "/a" in cmd
    assert "/b" in cmd


def test_build_cmd_omits_add_dir_when_disabled() -> None:
    agent = _make_agent(mcp_filesystem_enabled=False, mcp_filesystem_paths=["/a"])
    cmd = agent._build_cmd("hello", new_session=True)
    assert "--add-dir" not in cmd


def test_build_cmd_resume_also_adds_dir_flags() -> None:
    agent = _make_agent(mcp_filesystem_enabled=True, mcp_filesystem_paths=["/a"])
    agent._session_id = "thread-123"
    cmd = agent._build_cmd("hello", new_session=False)
    assert "--add-dir" in cmd
    assert "/a" in cmd
    assert "--full-auto" in cmd
