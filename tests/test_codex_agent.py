from kollab.agents.codex_agent import CodexAgent


def _make_agent(model: str = "test-model", **kwargs) -> CodexAgent:
    return CodexAgent(
        role="producer",
        binary="codex",
        model=model,
        workdir="/tmp/workdir",
        **kwargs,
    )


def test_build_cmd_uses_approve_for_me_not_bypass() -> None:
    """`--full-auto` was removed from the installed codex CLI (confirmed:
    v0.155.1 errors with "unexpected argument '--full-auto'") — replaced
    with `--approve-for-me`, which the CLI docs describe as auto-approving
    via the workspace-write sandbox, the same effective policy."""
    agent = _make_agent()
    cmd = agent._build_cmd("hello", new_session=True)
    assert "--approve-for-me" in cmd
    assert "--full-auto" not in cmd
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


def test_build_cmd_resume_omits_add_dir_and_approval_flags() -> None:
    """`codex exec resume` accepts neither --add-dir nor --approve-for-me/
    --full-auto (confirmed: both error with "unexpected argument" on
    v0.155.1) — the resumed thread keeps the directory access and sandbox
    policy set when it was created via the new-session branch."""
    agent = _make_agent(mcp_filesystem_enabled=True, mcp_filesystem_paths=["/a"])
    agent._session_id = "thread-123"
    cmd = agent._build_cmd("hello", new_session=False)
    assert "--add-dir" not in cmd
    assert "--approve-for-me" not in cmd
    assert "--full-auto" not in cmd


def test_build_cmd_includes_model_flag_when_set() -> None:
    agent = _make_agent(model="gpt-5.4")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-m" in cmd
    assert "gpt-5.4" in cmd


def test_build_cmd_omits_model_flag_when_whitespace_only() -> None:
    """A whitespace-only override is truthy in Python, so without stripping
    it would send `-m ' '` instead of omitting the flag, breaking the
    account-default fallback."""
    agent = _make_agent(model="   ")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-m" not in cmd


def test_build_cmd_omits_model_flag_when_blank() -> None:
    """Blank model means 'let Codex resolve its own account default' — see
    DEFAULT_CODEX_MODEL in config.py. Confirmed via `codex exec -m mini` (fails
    with a 400) and `codex exec -m gpt-5.4` (silently degrades with a stale
    metadata warning) that Codex has no safe alias to pin instead."""
    agent = _make_agent(model="")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-m" not in cmd


def test_build_cmd_includes_reasoning_effort_when_model_and_effort_set() -> None:
    agent = _make_agent(model="gpt-6-sol", reasoning_effort="low")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-c" in cmd
    assert "model_reasoning_effort=low" in cmd


def test_build_cmd_omits_reasoning_effort_when_model_blank() -> None:
    """Account-default should leave Codex's own defaults alone end to end —
    a reasoning override with no explicit model doesn't make sense."""
    agent = _make_agent(model="", reasoning_effort="low")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-c" not in cmd


def test_build_cmd_omits_reasoning_effort_when_not_set() -> None:
    agent = _make_agent(model="gpt-6-sol", reasoning_effort="")
    cmd = agent._build_cmd("hello", new_session=True)
    assert "-c" not in cmd
