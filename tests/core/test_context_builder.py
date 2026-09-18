"""ContextBuilder: clipping, summary stubs, pruning budget, build order.

(Replaces the pre-summary tests: stubs now KEEP the gist after
TOOL_STUB, which is the anti-re-run fix.)"""

from __future__ import annotations

from jimmy.context import SYSTEM_PROMPT, TOOL_STUB, ContextBuilder
from jimmy.llm.types import Message


def _tool(msg_id: str, content: str) -> Message:
    return Message(role="tool", content=content, tool_call_id=msg_id)


# ── clipping ───────────────────────────────────────────────────────────


def test_clip_short_output_untouched() -> None:
    cb = ContextBuilder()
    assert cb.clip_tool_output("short") == "short"


def test_clip_keeps_head_and_tail() -> None:
    cb = ContextBuilder(max_tool_output=100)
    out = cb.clip_tool_output("A" * 60 + "\nMIDDLE\n" + "B" * 60)
    assert out.startswith("A")
    assert out.endswith("B")
    assert "truncated" in out


# ── pruning: old tools summarized, not amnesia'd ──────────────────────


def test_old_tool_stub_contains_tool_stub_and_gist() -> None:
    cb = ContextBuilder(keep_raw_tools=1)
    history = [
        Message(role="user", content="go"),
        Message(role="assistant", content=""),
        _tool("a", "README.md | 12 ++\napp.py | 40 +++"),
        Message(role="assistant", content=""),
        _tool("b", "recent result"),
    ]
    view = cb.prune(history)

    stub = view[2].content
    assert stub.startswith(TOOL_STUB)  # stable public constant
    assert "README.md | 12 ++" in stub  # gist preserved → no re-runs
    assert "Do not re-run" in stub
    assert view[4].content == "recent result"  # recent stays raw


def test_prune_respects_budget() -> None:
    cb = ContextBuilder(keep_raw_tools=2)
    history = [
        _tool("1", "one"),
        Message(role="assistant", content=""),
        _tool("2", "two"),
        Message(role="assistant", content=""),
        _tool("3", "three"),
    ]
    view = cb.prune(history)

    assert view[0].content.startswith(TOOL_STUB)  # oldest → stub
    assert view[2].content == "two"  # within budget
    assert view[4].content == "three"  # newest raw


def test_prune_keeps_order_and_non_tool_messages() -> None:
    cb = ContextBuilder(keep_raw_tools=0)
    history = [
        Message(role="user", content="u1"),
        _tool("1", "t1"),
        Message(role="assistant", content="a1"),
    ]
    view = cb.prune(history)

    assert [m.role for m in view] == ["user", "tool", "assistant"]
    assert view[1].content.startswith(TOOL_STUB)


# ── build ──────────────────────────────────────────────────────────────


def test_build_prepends_system_and_appends_user() -> None:
    cb = ContextBuilder()
    messages = cb.build("do the thing")

    assert messages[0].role == "system"
    assert messages[0].content == SYSTEM_PROMPT
    assert messages[-1].role == "user"
    assert messages[-1].content == "do the thing"


def test_system_prompt_has_discipline_rules() -> None:
    low = SYSTEM_PROMPT.lower()
    assert "exactly" in low and "nothing more" in low
    assert "one commit per file" in low
    assert "never repeat a tool call" in low
    assert "batch" in low
