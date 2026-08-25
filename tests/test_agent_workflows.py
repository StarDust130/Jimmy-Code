import subprocess
from pathlib import Path

from jimmy.agent.agent_loop import AgentLoop
from jimmy.git.state import GitState
from jimmy.llm.base import (
    LLMProvider,
    LLMResponse,
    ToolCall,
)
from jimmy.permissions.manager import (
    PermissionManager,
    PermissionMode,
)
from jimmy.tools.defaults import create_default_registry


class FakeLLM(LLMProvider):
    """Deterministic LLM used to test the full agent loop."""

    def __init__(
        self,
        responses: list[LLMResponse],
    ) -> None:
        self.responses = responses
        self.index = 0

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        if self.index >= len(self.responses):
            raise RuntimeError("FakeLLM ran out of responses.")

        response = self.responses[self.index]
        self.index += 1

        return response


def init_git_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init"],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.email",
            "test@example.com",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "config",
            "user.name",
            "Jimmy Test",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )


def create_initial_commit(path: Path) -> None:
    subprocess.run(
        ["git", "add", "."],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )

    subprocess.run(
        [
            "git",
            "commit",
            "-m",
            "initial",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )


def edit_tool_call(
    call_id: str = "edit-1",
) -> LLMResponse:
    call = ToolCall(
        id=call_id,
        name="edit_file",
        arguments={
            "path": "example.txt",
            "old_text": "hello",
            "new_text": "hello Jimmy",
        },
    )

    return LLMResponse(
        content="",
        tool_calls=[call],
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "edit_file",
                        "arguments": (
                            '{"path":"example.txt","old_text":"hello","new_text":"hello Jimmy"}'
                        ),
                    },
                }
            ],
        },
    )


def git_commit_tool_call(
    call_id: str = "commit-1",
) -> LLMResponse:
    call = ToolCall(
        id=call_id,
        name="git_commit",
        arguments={
            "mode": "each",
            "scope": "jimmy",
        },
    )

    return LLMResponse(
        content="",
        tool_calls=[call],
        assistant_message={
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "git_commit",
                        "arguments": ('{"mode":"each","scope":"jimmy"}'),
                    },
                }
            ],
        },
    )


def final_response(
    text: str = "Done.",
) -> LLMResponse:
    return LLMResponse(
        content=text,
        tool_calls=[],
        assistant_message={
            "role": "assistant",
            "content": text,
        },
    )


def git_log(path: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "log",
            "--oneline",
            "-1",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    return result.stdout.strip()


def git_status(path: Path) -> str:
    result = subprocess.run(
        [
            "git",
            "status",
            "--short",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    return result.stdout.strip()


def test_edit_then_commit(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)

    file = tmp_path / "example.txt"

    file.write_text(
        "hello\n",
        encoding="utf-8",
    )

    create_initial_commit(tmp_path)

    git_state = GitState(tmp_path)

    llm = FakeLLM(
        [
            edit_tool_call(),
            git_commit_tool_call(),
            final_response("Done. Edited and committed example.txt."),
        ]
    )

    tools = create_default_registry(
        root=tmp_path,
        llm=None,
        git_state=git_state,
    )

    permissions = PermissionManager(
        mode=PermissionMode.FULL_ACCESS,
    )

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=tmp_path,
        git_state=git_state,
        max_turns=5,
        permission_manager=permissions,
    )

    result = agent.run("Edit example.txt and commit it.")

    assert (
        file.read_text(
            encoding="utf-8",
        )
        == "hello Jimmy\n"
    )

    assert result == "Done. Edited and committed example.txt."

    log = git_log(tmp_path)

    assert log

    assert git_status(tmp_path) == ""


def test_commit_then_continue(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)

    file = tmp_path / "example.txt"

    file.write_text(
        "hello\n",
        encoding="utf-8",
    )

    create_initial_commit(tmp_path)

    git_state = GitState(tmp_path)

    file.write_text(
        "hello Jimmy\n",
        encoding="utf-8",
    )

    llm = FakeLLM(
        [
            git_commit_tool_call(),
            final_response("Done. The changes were committed and I continued."),
        ]
    )

    tools = create_default_registry(
        root=tmp_path,
        llm=None,
        git_state=git_state,
    )

    permissions = PermissionManager(
        mode=PermissionMode.FULL_ACCESS,
    )

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=tmp_path,
        git_state=git_state,
        max_turns=5,
        permission_manager=permissions,
    )

    result = agent.run("Commit my changes, then continue.")

    assert result == "Done. The changes were committed and I continued."

    assert llm.index == 2

    assert git_log(tmp_path)

    assert git_status(tmp_path) == ""
