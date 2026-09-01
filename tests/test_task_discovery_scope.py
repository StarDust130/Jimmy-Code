from pathlib import Path

from jimmy.agent.main_loop.agent_tool_guard import ToolGuard
from jimmy.agent.task_state_builder import build_task_state
from jimmy.state.session import SessionState


def test_discovery_cannot_escape_explicit_project_scope(tmp_path: Path) -> None:
    state = build_task_state(
        "Create a folder called gitGraph and work only inside that folder "
        "using HTML, CSS, and JavaScript.",
        tmp_path,
    )
    session = SessionState(task=state.task)

    for tool_name, arguments in (
        ("search_files", {"query": "task", "path": "src/jimmy"}),
        ("read_file", {"path": "tests/test_agent.py"}),
        ("verify_frontend", {"directory": "src"}),
    ):
        decision = ToolGuard(tmp_path).check(
            tool_name,
            arguments,
            session,
            state,
        )
        assert decision.allowed is False
        assert "outside" in decision.reason


def test_discovery_inside_project_remains_allowed(tmp_path: Path) -> None:
    state = build_task_state(
        "Create a folder called gitGraph and work only inside that folder "
        "using HTML, CSS, and JavaScript.",
        tmp_path,
    )
    decision = ToolGuard(tmp_path).check(
        "search_files",
        {"query": "graph", "path": "gitGraph"},
        SessionState(task=state.task),
        state,
    )
    assert decision.allowed is True
