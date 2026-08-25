from pathlib import Path

from jimmy.session.json_store import JsonSessionStore
from jimmy.state.session import SessionState


def test_save_and_load_session(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path)

    state = SessionState(
        task="Inspect the project",
        messages=[
            {
                "role": "user",
                "content": "Inspect the project",
            },
            {
                "role": "assistant",
                "content": "I will inspect it.",
            },
        ],
    )

    state.turn_count = 2

    session_id = store.create(state)

    # Verify the file can be loaded again.
    restored = store.load(session_id)

    assert restored.task == state.task
    assert restored.messages == state.messages
    assert restored.turn_count == 2


def test_list_sessions(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path)

    state = SessionState(
        task="Test task",
        messages=[],
    )

    session_id = store.create(state)

    sessions = store.list()

    assert len(sessions) == 1
    assert sessions[0]["id"] == session_id
    assert sessions[0]["task"] == "Test task"
    assert sessions[0]["status"] == "running"


def test_delete_session(
    tmp_path: Path,
) -> None:
    store = JsonSessionStore(tmp_path)

    state = SessionState(
        task="Delete me",
        messages=[],
    )

    session_id = store.create(state)

    store.delete(session_id)

    assert store.list() == []
