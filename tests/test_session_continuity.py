from pathlib import Path

from jimmy.agent.main_loop.agent_loop import AgentLoop
from jimmy.llm.base import (
    LLMProvider,
    LLMResponse,
)
from jimmy.session.json_store import JsonSessionStore
from jimmy.tools.defaults import create_default_registry


class FakeLLM(LLMProvider):
    def __init__(
        self,
        responses: list[LLMResponse],
    ) -> None:
        self.responses = responses
        self.index = 0
        self.seen_messages: list[list[dict]] = []

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        self.seen_messages.append(messages)

        response = self.responses[self.index]

        self.index += 1

        return response


def test_continue_session_keeps_previous_messages(
    tmp_path: Path,
) -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content="Done with the first task.",
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": "Done with the first task.",
                },
            ),
            LLMResponse(
                content="Yes, I remember the previous file.",
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": "Yes, I remember the previous file.",
                },
            ),
        ]
    )

    tools = create_default_registry(
        root=tmp_path,
        llm=None,
    )

    store = JsonSessionStore(tmp_path)

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=tmp_path,
        session_store=store,
        max_turns=5,
    )

    first_result = agent.run("Add a comment to main.py.")

    assert first_result == ("Done with the first task.")

    session_id = agent.current_session_id

    assert session_id is not None

    second_result = agent.continue_session(
        session_id=session_id,
        task="Commit that file.",
    )

    assert second_result == ("Yes, I remember the previous file.")

    assert store.load(session_id).task == "Commit that file."

    second_context = llm.seen_messages[1]

    user_messages = [message for message in second_context if message.get("role") == "user"]

    assert user_messages == [
        {
            "role": "user",
            "content": ("Add a comment to main.py."),
        },
        {
            "role": "user",
            "content": ("Commit that file."),
        },
    ]


def test_new_run_creates_new_conversation(
    tmp_path: Path,
) -> None:
    llm = FakeLLM(
        [
            LLMResponse(
                content="first",
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": "first",
                },
            ),
            LLMResponse(
                content="second",
                tool_calls=[],
                assistant_message={
                    "role": "assistant",
                    "content": "second",
                },
            ),
        ]
    )

    tools = create_default_registry(
        root=tmp_path,
        llm=None,
    )

    store = JsonSessionStore(tmp_path)

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=tmp_path,
        session_store=store,
        max_turns=5,
    )

    agent.run("First task")

    first_session_id = agent.current_session_id

    agent.run("Completely new task")

    second_session_id = agent.current_session_id

    assert first_session_id is not None
    assert second_session_id is not None

    assert first_session_id != second_session_id

    second_context = llm.seen_messages[1]

    user_messages = [message for message in second_context if message.get("role") == "user"]

    assert user_messages == [
        {
            "role": "user",
            "content": ("Completely new task"),
        },
    ]
