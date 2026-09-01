from pathlib import Path

from jimmy.agent.task_state_builder import build_task_state


def test_static_project_scope_ignores_url_examples(tmp_path: Path) -> None:
    state = build_task_state(
        "Create a folder called gitGraph and work only inside that folder. "
        "Build it using HTML, CSS, and JavaScript. Fetch "
        "https://api.github.com/users/{USERNAME}/events/public and make "
        "https://YOUR-DOMAIN.com/graph?user=USERNAME.",
        tmp_path,
    )

    assert state.requested_paths == {"gitGraph"}
    assert state.static_frontend is True
    assert state.shell_requested is False
