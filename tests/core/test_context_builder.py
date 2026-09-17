"""🧪 Context builder: clipping + pruning + build."""

from jimmy.context import TOOL_STUB
from jimmy.context.builder import ContextBuilder
from jimmy.llm.types import Message, ToolCall


def make_tool_msgs(n: int) -> list[Message]:
    """Build fake loop history: n (assistant-with-tool-call, tool-result) pairs."""
    msgs: list[Message] = []
    for i in range(n):
        msgs.append(
            Message(
                role="assistant",
                content="",
                tool_calls=(ToolCall(id=f"c{i}", name="read", arguments={}),),
            )
        )
        msgs.append(Message(role="tool", content=f"output {i}", tool_call_id=f"c{i}"))
    return msgs


# ───────────────────────────
# ✂️ clipping
# ───────────────────────────


def test_short_output_untouched():
    cb = ContextBuilder()
    assert cb.clip_tool_output("small") == "small"


def test_long_output_clipped_with_marker():
    cb = ContextBuilder(max_tool_output=100)
    out = cb.clip_tool_output("x" * 10_000)

    assert len(out) < 300
    assert "truncated" in out


# ───────────────────────────
# 🧹 pruning
# ───────────────────────────


def test_recent_tools_stay_raw():
    cb = ContextBuilder(keep_raw_tools=2)
    msgs = make_tool_msgs(5)

    pruned = cb.prune(msgs)

    raw = [m for m in pruned if m.role == "tool" and m.content != TOOL_STUB]
    stubbed = [m for m in pruned if m.role == "tool" and m.content == TOOL_STUB]

    assert len(raw) == 2                    # 🎯 only last 2 stay raw
    assert len(stubbed) == 3                # 🪦 older ones stubbed
    assert raw[-1].content == "output 4"    # newest survived


def testprune_preserves_order_and_non_tool_msgs():
    cb = ContextBuilder(keep_raw_tools=1)
    msgs = [
        Message(role="user", content="hi"),
        *make_tool_msgs(3),
        Message(role="user", content="next"),
    ]

    pruned = cb.prune(msgs)

    assert pruned[0].content == "hi"    # 📏 order preserved
    assert pruned[-1].content == "next"
    assert len(pruned) == len(msgs)     # 📏 nothing dropped, only stubbed


# ───────────────────────────
# 🏗️ build
# ───────────────────────────


def test_build_has_system_user_andpruned_history():
    cb = ContextBuilder(keep_raw_tools=1)
    history = make_tool_msgs(4)

    built = cb.build("fix the bug", history)

    assert built[0].role == "system"
    assert built[-1].role == "user"
    assert built[-1].content == "fix the bug"

    stubbed = [m for m in built if m.role == "tool" and m.content == TOOL_STUB]
    assert len(stubbed) == 3    # 4 tool results → 3 stubbed, 1 raw