"""🗄️ SessionStore — CRUD · ordering · rename · cascade · settings · cleanup."""

from __future__ import annotations

import concurrent.futures
import time
from datetime import datetime, timedelta, timezone

import pytest

import jimmy.sessions.store as store_module
from jimmy.sessions import CLEANUP_CHOICES, SessionStore


@pytest.fixture()
def store(tmp_path):
    s = SessionStore(tmp_path / "s.db")
    yield s
    s.close()


# ── sessions ────────────────────────────────────────────────────────────


def test_create_and_list_newest_first(store) -> None:
    a = store.create_session(title="a")
    time.sleep(0.01)
    b = store.create_session(title="b")
    time.sleep(0.01)
    c = store.create_session(title="c")

    rows = store.list_sessions()
    assert [r.id for r in rows] == [c.id, b.id, a.id]
    assert rows[0].title == "c"
    assert rows[0].message_count == 0


def test_append_messages_orders_and_counts(store) -> None:
    sid = store.create_session().id
    store.append_message(sid, "user", "first")
    store.append_message(
        sid,
        "assistant",
        "reply",
        tool_calls=[{"id": "c1", "name": "shell", "arguments": {"command": "ls"}}],
    )
    store.append_message(sid, "user", "second")

    msgs = store.get_messages(sid)
    assert [m.role for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1].tool_calls[0]["name"] == "shell"
    assert store.count_user_messages(sid) == 2
    assert store.get_session(sid).message_count == 3


def test_rename_sets_user_source_and_blocks_auto(store) -> None:
    sid = store.create_session().id
    assert store.rename_session(sid, "my name") is True
    row = store.get_session(sid)
    assert row.title == "my name"
    assert row.title_source == "user"

    # 🔒 a user rename is never overwritten by AI titles
    assert store.set_auto_title(sid, "ai thinks otherwise") is False
    assert store.get_session(sid).title == "my name"


def test_auto_title_applies_to_default_and_auto(store) -> None:
    sid = store.create_session().id
    assert store.get_session(sid).title_source == "default"
    assert store.set_auto_title(sid, "first auto title") is True
    assert store.get_session(sid).title_source == "auto"
    assert store.set_auto_title(sid, "second auto title") is True
    assert store.get_session(sid).title == "second auto title"


def test_delete_cascades_everything(store) -> None:
    sid = store.create_session().id
    store.append_message(sid, "user", "hello")
    row_id = store.tool_started(sid, "c1", "shell", {"command": "ls"})
    store.tool_finished(row_id, "out", 5.0)
    store.append_event(sid, "error", "boom")

    assert store.delete_session(sid) is True
    assert store.get_session(sid) is None
    assert store.get_messages(sid) == []
    assert store.get_tool_outputs(sid) == {}
    assert store.list_sessions() == []


def test_touch_updates_model_and_permission(store) -> None:
    sid = store.create_session(model="old", permission_mode="auto").id
    assert store.touch_session(sid, model="new-model", permission_mode="full") is True
    row = store.get_session(sid)
    assert row.model == "new-model"
    assert row.permission_mode == "full"


# ── settings + cleanup ──────────────────────────────────────────────────


def test_settings_roundtrip_and_default(store) -> None:
    assert store.get_setting("cleanup_days") == "30"  # default
    store.set_setting("cleanup_days", "90")
    assert store.get_setting("cleanup_days") == "90"
    assert store.get_setting("unknown-key") == ""


def test_cleanup_days_validation(store) -> None:
    for raw in CLEANUP_CHOICES:
        store.set_cleanup_days(raw)
        if raw == "never":
            assert store.cleanup_days() is None
        else:
            assert store.cleanup_days() == int(raw)
    with pytest.raises(ValueError):
        store.set_cleanup_days("7")


def test_cleanup_30_days(monkeypatch, store) -> None:
    monkeypatch.setattr(
        store_module,
        "_now",
        lambda: (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(
            timespec="milliseconds"
        ),
    )
    stale = store.create_session(title="stale")
    monkeypatch.undo()
    fresh = store.create_session(title="fresh")

    assert store.cleanup(30) == 1
    assert store.get_session(stale.id) is None
    assert store.get_session(fresh.id) is not None


def test_cleanup_15_days(monkeypatch, store) -> None:
    monkeypatch.setattr(
        store_module,
        "_now",
        lambda: (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(
            timespec="milliseconds"
        ),
    )
    stale = store.create_session(title="stale")
    monkeypatch.undo()
    store.create_session(title="fresh")
    assert store.cleanup(15) == 1


def test_cleanup_never_and_manual_delete(monkeypatch, store) -> None:
    monkeypatch.setattr(
        store_module,
        "_now",
        lambda: (datetime.now(timezone.utc) - timedelta(days=3650)).isoformat(
            timespec="milliseconds"
        ),
    )
    ancient = store.create_session(title="ancient")
    monkeypatch.undo()

    assert store.cleanup(None) == 0
    assert store.cleanup(0) == 0

    store.set_cleanup_days("never")
    assert store.cleanup_days() is None
    assert store.cleanup(store.cleanup_days()) == 0

    # manual deletion is ALWAYS available, even with policy=never
    assert store.delete_session(ancient.id) is True


# ── persistence + concurrency ───────────────────────────────────────────


def test_persistence_across_reopen(tmp_path) -> None:
    path = tmp_path / "s.db"
    first = SessionStore(path)
    sid = first.create_session(title="kept").id
    first.append_message(sid, "user", "survives restart")
    first.close()

    second = SessionStore(path)
    row = second.get_session(sid)
    assert row is not None and row.title == "kept"
    assert [m.content for m in second.get_messages(sid)] == ["survives restart"]
    second.close()


def test_thread_safety_concurrent_appends(store) -> None:
    sid = store.create_session().id

    def burst(i: int) -> None:
        for j in range(20):
            store.append_message(sid, "user", f"t{i}-{j}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(burst, range(4)))

    msgs = store.get_messages(sid)
    assert len(msgs) == 80
    seqs = [m.seq for m in msgs]
    assert len(set(seqs)) == 80  # unique — no lost updates
    assert store.get_session(sid).message_count == 80


def test_build_history_reconstructs_tool_loop(store) -> None:
    sid = store.create_session().id
    store.append_message(sid, "user", "run ls")
    store.append_message(
        sid,
        "assistant",
        "",
        tool_calls=[{"id": "c1", "name": "shell", "arguments": {"command": "ls"}}],
    )
    row = store.tool_started(sid, "c1", "shell", {"command": "ls"})
    store.tool_finished(row, "a.py\nb.py", 9.0)
    store.append_message(sid, "assistant", "here are your files")

    history = store.build_history(sid)
    assert [m.role for m in history] == ["user", "assistant", "tool", "assistant"]
    assert history[1].tool_calls[0].name == "shell"
    assert history[2].tool_call_id == "c1"
    assert history[2].content == "a.py\nb.py"
    assert history[3].content == "here are your files"
