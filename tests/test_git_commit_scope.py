from __future__ import annotations

from pathlib import Path

from jimmy.agent.main_loop.agent_tool_guard import ToolGuard
from jimmy.agent.task_state import TaskState


def make_guard(
    tmp_path: Path,
) -> ToolGuard:
    return ToolGuard(
        workspace=tmp_path,
    )


def make_state(
    tmp_path: Path,
    task: str,
    paths: set[str],
    *,
    commit_requested: bool,
) -> TaskState:
    return TaskState(
        task=task,
        workspace=tmp_path,
        requested_paths=paths,
        commit_requested=commit_requested,
    )


def check(
    guard: ToolGuard,
    tool_name: str,
    arguments: dict,
    task_state: TaskState,
):
    return guard.check(
        tool_name=tool_name,
        arguments=arguments,
        state=None,  # type: ignore[arg-type]
        task_state=task_state,
    )


def test_specific_commit_path_is_allowed(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Commit main.py only.",
        {"main.py"},
        commit_requested=True,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": ["main.py"],
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is True


def test_commit_outside_scope_is_blocked(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Commit main.py only.",
        {"main.py"},
        commit_requested=True,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": ["other.py"],
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is False
    assert "outside" in decision.reason


def test_mixed_commit_scope_is_blocked(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Commit main.py only.",
        {"main.py"},
        commit_requested=True,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": [
                "main.py",
                "other.py",
            ],
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is False
    assert "outside" in decision.reason


def test_omitted_commit_paths_are_blocked_for_explicit_scope(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Commit main.py only.",
        {"main.py"},
        commit_requested=True,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": None,
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is False
    assert "explicit file scope" in decision.reason


def test_all_commit_is_allowed_without_explicit_scope(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Commit all changed files one by one.",
        set(),
        commit_requested=True,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": None,
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is True


def test_commit_is_blocked_when_not_requested(
    tmp_path: Path,
) -> None:
    guard = make_guard(tmp_path)

    state = make_state(
        tmp_path,
        "Fix main.py.",
        {"main.py"},
        commit_requested=False,
    )

    decision = check(
        guard,
        "git_commit",
        {
            "paths": ["main.py"],
            "mode": "each",
        },
        state,
    )

    assert decision.allowed is False
    assert "not requested" in decision.reason