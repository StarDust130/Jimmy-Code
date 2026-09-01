"""Deterministic production-agent regression evals.

These use the real AgentLoop and filesystem tools.  The scripted provider only
supplies decisions; before every decision it validates the exact history that
would be sent to Gemini.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from jimmy.agent.main_loop.agent_loop import AgentLoop
from jimmy.context.context import ContextConfig, ContextManager
from jimmy.llm.base import LLMProvider, LLMResponse, ToolCall
from jimmy.llm.gemini import GeminiProvider
from jimmy.permissions.manager import PermissionManager, PermissionMode
from jimmy.session.json_store import JsonSessionStore
from jimmy.tools.defaults import create_default_registry


def response_for(*calls: ToolCall) -> LLMResponse:
    serialized = [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments),
            },
        }
        for call in calls
    ]
    return LLMResponse(
        content="",
        tool_calls=list(calls),
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": serialized,
        },
    )


def final(text: str = "Done.") -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=[],
        assistant_message={"role": "assistant", "content": text},
    )


def call(
    identifier: str,
    name: str,
    **arguments: Any,
) -> ToolCall:
    return ToolCall(id=identifier, name=name, arguments=arguments)


class GeminiHistoryCheckingLLM(LLMProvider):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = responses
        self.requests: list[list[dict[str, Any]]] = []

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        del tools
        GeminiProvider._prepare_contents_for_request(
            GeminiProvider._convert_messages(messages)[1]
        )
        self.requests.append(messages)
        return self.responses.pop(0)


def make_agent(
    tmp_path: Path,
    responses: list[LLMResponse],
    *,
    max_turns: int = 20,
) -> tuple[AgentLoop, GeminiHistoryCheckingLLM]:
    llm = GeminiHistoryCheckingLLM(responses)
    agent = AgentLoop(
        llm=llm,
        tools=create_default_registry(root=tmp_path),
        workspace=tmp_path,
        max_turns=max_turns,
        permission_manager=PermissionManager(PermissionMode.FULL_ACCESS),
        session_store=JsonSessionStore(tmp_path),
    )
    return agent, llm


def test_eval_simple_file_creation(tmp_path: Path) -> None:
    agent, _ = make_agent(
        tmp_path,
        [
            response_for(
                call(
                    "create",
                    "create_files",
                    files=[{"path": "a.txt", "content": "hello"}],
                )
            ),
            final(),
        ],
    )
    agent.run("Create a.txt.")
    assert (tmp_path / "a.txt").read_text() == "hello"


def test_eval_repeated_edits_to_same_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n")
    agent, _ = make_agent(
        tmp_path,
        [
            response_for(call("edit-1", "edit_file", path="a.txt", old_text="one", new_text="two")),
            response_for(call("edit-2", "edit_file", path="a.txt", old_text="two", new_text="three")),
            final(),
        ],
    )
    agent.run("Edit a.txt twice.")
    assert (tmp_path / "a.txt").read_text() == "three\n"


def test_eval_multiple_files_in_one_function_batch(tmp_path: Path) -> None:
    agent, _ = make_agent(
        tmp_path,
        [
            response_for(
                call("one", "create_files", files=[{"path": "one.txt", "content": "1"}]),
                call("two", "create_files", files=[{"path": "two.txt", "content": "2"}]),
            ),
            final(),
        ],
    )
    agent.run("Create one.txt and two.txt.")
    assert (tmp_path / "one.txt").read_text() == "1"
    assert (tmp_path / "two.txt").read_text() == "2"


def test_eval_tool_failure_then_recovery(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n")
    agent, _ = make_agent(
        tmp_path,
        [
            response_for(call("bad", "edit_file", path="a.txt", old_text="missing", new_text="two")),
            response_for(call("good", "edit_file", path="a.txt", old_text="one", new_text="two")),
            final(),
        ],
    )
    agent.run("Update a.txt.")
    assert (tmp_path / "a.txt").read_text() == "two\n"


def test_eval_legitimate_repeated_commands_are_not_blocked(tmp_path: Path) -> None:
    agent, llm = make_agent(
        tmp_path,
        [
            response_for(call("pwd-1", "run_shell", command="pwd")),
            response_for(call("pwd-2", "run_shell", command="pwd")),
            final(),
        ],
    )
    agent.run("Run pwd twice.")
    assert len(llm.requests) == 3


def test_eval_repeated_failed_loop_is_blocked_but_history_stays_valid(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("one\n")
    failed_edit = {"path": "a.txt", "old_text": "missing", "new_text": "two"}
    agent, llm = make_agent(
        tmp_path,
        [
            response_for(call("bad-1", "edit_file", **failed_edit)),
            response_for(call("bad-2", "edit_file", **failed_edit)),
            response_for(call("bad-3", "edit_file", **failed_edit)),
            final("Blocked loop reported."),
        ],
    )
    assert agent.run("Update a.txt.") == "Blocked loop reported."
    assert len(llm.requests) == 4


def test_regression_blocked_call_in_multi_tool_batch_has_every_response(tmp_path: Path) -> None:
    """The old guard raised after one response and orphaned later calls."""
    (tmp_path / "a.txt").write_text("one\n")
    failed_edit = {"path": "a.txt", "old_text": "missing", "new_text": "two"}
    agent, llm = make_agent(
        tmp_path,
        [
            response_for(call("bad-1", "edit_file", **failed_edit)),
            response_for(call("bad-2", "edit_file", **failed_edit)),
            response_for(
                call("bad-3", "edit_file", **failed_edit),
                call("create", "create_files", files=[{"path": "recovered.txt", "content": "ok"}]),
            ),
            final(),
        ],
    )
    agent.run("Update a.txt and create recovered.txt.")
    assert (tmp_path / "recovered.txt").read_text() == "ok"
    third_turn = llm.requests[3]
    responses = [message for message in third_turn if message.get("role") == "tool"][-2:]
    assert {response["tool_call_id"] for response in responses} == {"bad-3", "create"}


def test_regression_gemini_rejects_the_previously_persisted_malformed_sequence() -> None:
    messages = [
        {"role": "user", "content": "Do work."},
        response_for(
            call("first", "read_file", path="a.txt"),
            call("second", "read_file", path="b.txt"),
        ).assistant_message,
        {"role": "tool", "tool_call_id": "first", "name": "read_file", "content": "ok"},
    ]
    with pytest.raises(ValueError, match="expected 2 tool response"):
        GeminiProvider._convert_messages(messages)


def test_eval_failed_verification_then_fix_and_reverify(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_value():\n    assert False\n")
    agent, _ = make_agent(
        tmp_path,
        [
            response_for(call("test-1", "run_shell", command="python -m pytest -q")),
            response_for(call("fix", "edit_file", path="test_sample.py", old_text="assert False", new_text="assert True")),
            response_for(call("test-2", "run_shell", command="python -m pytest -q")),
            final("Verified."),
        ],
    )
    assert agent.run("Fix the failing test and verify it.") == "Verified."


def test_eval_long_multi_step_task_with_many_tool_calls(tmp_path: Path) -> None:
    responses = [
        response_for(call(f"create-{index}", "create_files", files=[{"path": f"f{index}.txt", "content": str(index)}]))
        for index in range(12)
    ] + [final()]
    agent, llm = make_agent(tmp_path, responses)
    agent.run("Create twelve files.")
    assert len(llm.requests) == 13
    assert (tmp_path / "f11.txt").read_text() == "11"


def test_eval_context_compaction_preserves_function_call_anchor(tmp_path: Path) -> None:
    responses = [
        response_for(call(f"create-{index}", "create_files", files=[{"path": f"f{index}.txt", "content": str(index)}]))
        for index in range(5)
    ] + [final()]
    agent, llm = make_agent(tmp_path, responses)
    agent.main_loop.turn.context_manager = ContextManager(
        config=ContextConfig(max_messages=4, max_total_chars=1_000, compact_at_chars=900),
    )
    agent.run("Create several files.")
    assert len(llm.requests) == 6


def test_eval_gemini_history_many_function_turns(tmp_path: Path) -> None:
    responses = [
        response_for(call(f"read-{index}", "read_file", path="a.txt"))
        for index in range(10)
    ] + [final("Read repeatedly.")]
    (tmp_path / "a.txt").write_text("content")
    agent, llm = make_agent(tmp_path, responses)
    assert agent.run("Read a.txt repeatedly.") == "Read repeatedly."
    assert len(llm.requests) == 11
