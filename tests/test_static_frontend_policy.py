from pathlib import Path

from jimmy.agent.main_loop.agent_tool_guard import ToolGuard
from jimmy.agent.task_state_builder import build_task_state
from jimmy.state.session import SessionState


def test_static_frontend_rejects_shell_even_if_a_stale_schema_offers_it(
    tmp_path: Path,
) -> None:
    state = build_task_state(
        "Create a folder called gitGraph and work only inside that folder "
        "using HTML, CSS, and JavaScript.",
        tmp_path,
    )

    decision = ToolGuard(tmp_path).check(
        "run_shell",
        {"command": "python3 -m http.server"},
        SessionState(task="test"),
        state,
    )

    assert decision.allowed is False
    assert "static frontend" in decision.reason


def test_static_frontend_allows_shell_when_user_explicitly_requests_it(
    tmp_path: Path,
) -> None:
    state = build_task_state(
        "Fix the HTML, CSS, and JavaScript app and run npm test.",
        tmp_path,
    )

    decision = ToolGuard(tmp_path).check(
        "run_shell",
        {"command": "npm test"},
        SessionState(task="test"),
        state,
    )

    assert decision.allowed is True


def test_non_shell_edit_task_rejects_shell_even_if_stale_schema_offers_it(
    tmp_path: Path,
) -> None:
    state = build_task_state(
        "Add a comment above greeting in main.py.",
        tmp_path,
    )

    decision = ToolGuard(tmp_path).check(
        "run_shell",
        {"command": "cat main.py"},
        SessionState(task="test"),
        state,
    )

    assert decision.allowed is False
    assert "shell" in decision.reason.lower()
