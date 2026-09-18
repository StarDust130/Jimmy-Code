"""🗄️ SessionRecorder — event mirroring into the store."""

from __future__ import annotations

import pytest

from jimmy.sessions import SessionRecorder, SessionStore


@pytest.fixture()
def rec(tmp_path):
    store = SessionStore(tmp_path / "s.db")
    sid = store.create_session().id
    yield store, SessionRecorder(store, sid)
    store.close()


def test_user_then_assistant_steps(rec) -> None:
    store, recorder = rec
    recorder.user_message("hi")
    recorder.begin_step()
    recorder.step_text("I'll ")
    recorder.step_text("check")
    recorder.begin_step()  # flushes the pending assistant
    recorder.step_text("done")
    recorder.assistant_flush()

    msgs = store.get_messages(recorder.session_id)
    assert [m.role for m in msgs] == ["user", "assistant", "assistant"]
    assert msgs[1].content == "I'll check"
    assert msgs[2].content == "done"
    assert msgs[1].tool_calls == []


def test_tool_lifecycle_recorded(rec) -> None:
    store, recorder = rec
    recorder.begin_step()
    recorder.step_text("running it")
    recorder.tool_started("c1", "shell", {"command": "ls"})
    recorder.tool_finished("c1", "a.py\nb.py", 12.5)
    recorder.assistant_flush()

    sid = recorder.session_id
    assert store.get_tool_outputs(sid) == {"c1": "a.py\nb.py"}

    assistant = [m for m in store.get_messages(sid) if m.role == "assistant"][0]
    assert assistant.tool_calls == [{"id": "c1", "name": "shell", "arguments": {"command": "ls"}}]


def test_error_and_denied_status(rec) -> None:
    store, recorder = rec
    recorder.tool_started("c1", "shell", {"command": "rm -rf /"})
    recorder.tool_failed("c1", ValueError("nope"))
    recorder.tool_started("c2", "git", {"command": "push"})
    recorder.tool_denied("c2")

    with store._lock:
        rows = store._conn.execute(
            "SELECT call_id, status, output FROM tool_calls ORDER BY id"
        ).fetchall()
    by_id = {r["call_id"]: r for r in rows}
    assert by_id["c1"]["status"] == "error"
    assert "ValueError" in by_id["c1"]["output"]
    assert by_id["c2"]["status"] == "denied"
    assert "denied" in by_id["c2"]["output"]


def test_build_history_after_recording(rec) -> None:
    store, recorder = rec
    recorder.user_message("commit please")
    recorder.begin_step()
    recorder.step_text("on it")
    recorder.tool_started("c1", "git", {"command": "status"})
    recorder.tool_finished("c1", "nothing to commit", 3.0)
    recorder.begin_step()
    recorder.step_text("committed")
    recorder.assistant_flush()

    history = store.build_history(recorder.session_id)
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[2].content == "nothing to commit"
    assert history[2].tool_call_id == "c1"


def test_recorder_survives_deleted_session(rec) -> None:
    store, recorder = rec
    store.delete_session(recorder.session_id)
    recorder.user_message("into the void")  # must not raise
    recorder.assistant_flush()
    recorder.event("error", "whatever")
