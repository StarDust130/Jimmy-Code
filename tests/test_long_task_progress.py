from __future__ import annotations

from jimmy.agent.main_loop.agent_progress import AgentProgress


def test_progress_records_successful_tools() -> None:
    progress = AgentProgress()

    progress.start_turn(7)

    progress.record(
        "read_file",
        {
            "path": "main.py",
        },
        success=True,
    )

    progress.record(
        "edit_file",
        {
            "path": "main.py",
        },
        success=True,
        changed_workspace=True,
    )

    summary = progress.context_summary()

    assert "turn=7" in summary
    assert "tool_calls=2" in summary
    assert "successful=2" in summary
    assert "successful_mutations=1" in summary
    assert "main.py" in summary


def test_progress_records_failures() -> None:
    progress = AgentProgress()

    progress.record(
        "run_shell",
        {
            "command": "pytest",
        },
        success=False,
    )

    summary = progress.context_summary()

    assert "failures=1" in summary
    assert "pytest" in summary


def test_progress_keeps_recent_actions_bounded() -> None:
    progress = AgentProgress()

    for index in range(20):
        progress.record(
            "read_file",
            {
                "path": f"file{index}.py",
            },
            success=True,
        )

    summary = progress.context_summary()

    assert "file19.py" in summary
    assert "file0.py" not in summary


def test_progress_changed_files_are_bounded() -> None:
    progress = AgentProgress()

    for index in range(50):
        progress.record(
            "edit_file",
            {
                "path": f"file{index}.py",
            },
            success=True,
            changed_workspace=True,
        )

    summary = progress.context_summary(
        max_chars=2500,
    )

    assert "file0.py" in summary
    assert "file19.py" in summary


def test_successful_action_clears_same_failure_history() -> None:
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

    allowed, _ = progress.can_run(
        "edit_file",
        arguments,
    )

    assert allowed is False

    progress.record(
        "edit_file",
        arguments,
        success=True,
        changed_workspace=True,
    )

    allowed, _ = progress.can_run(
        "edit_file",
        arguments,
    )

    assert allowed is True


def test_context_summary_is_compact() -> None:
    progress = AgentProgress()

    for index in range(100):
        progress.record(
            "run_shell",
            {
                "command": (
                    f"very-long-command-{index} "
                    "with lots of arguments "
                    "that should stay compact"
                ),
            },
            success=True,
        )

    summary = progress.context_summary(
        max_chars=1200,
    )

    assert len(summary) <= 1200
    assert "<task_progress>" in summary
    assert "</task_progress>" in summary