from jimmy.agent.main_loop.agent_progress import AgentProgress


def test_allows_first_action() -> None:
    progress = AgentProgress()

    allowed, reason = progress.can_run(
        "run_shell",
        {"command": "pytest"},
    )

    assert allowed is True
    assert reason == ""


def test_blocks_same_failed_action_after_limit() -> None:
    progress = AgentProgress()

    arguments = {
        "command": "pytest",
    }

    progress.record(
        "run_shell",
        arguments,
        success=False,
    )

    allowed, _ = progress.can_run(
        "run_shell",
        arguments,
    )
    assert allowed is True

    progress.record(
        "run_shell",
        arguments,
        success=False,
    )

    allowed, reason = progress.can_run(
        "run_shell",
        arguments,
    )

    assert allowed is False
    assert "same tool action" in reason


def test_different_action_is_allowed() -> None:
    progress = AgentProgress()

    progress.record(
        "run_shell",
        {"command": "pytest"},
        success=False,
    )

    progress.record(
        "run_shell",
        {"command": "pytest"},
        success=False,
    )

    allowed, _ = progress.can_run(
        "run_shell",
        {"command": "pytest -q"},
    )

    assert allowed is True


def test_success_clears_tool_failure_streak() -> None:
    progress = AgentProgress()

    arguments = {
        "command": "pytest",
    }

    progress.record(
        "run_shell",
        arguments,
        success=False,
    )

    progress.record(
        "run_shell",
        arguments,
        success=False,
    )

    progress.record(
        "run_shell",
        arguments,
        success=True,
    )

    allowed, _ = progress.can_run(
        "run_shell",
        arguments,
    )

    assert allowed is True


def test_workspace_change_clears_failure_history() -> None:
    progress = AgentProgress()

    arguments = {
        "path": "main.py",
    }

    progress.record(
        "edit_file",
        arguments,
        success=False,
    )

    progress.record(
        "edit_file",
        arguments,
        success=False,
    )

    progress.record(
        "edit_file",
        {"path": "main.py"},
        success=True,
        changed_workspace=True,
    )

    allowed, _ = progress.can_run(
        "edit_file",
        arguments,
    )

    assert allowed is True
