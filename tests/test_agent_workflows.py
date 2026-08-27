import subprocess
from pathlib import Path

from jimmy.agent.main_loop.agent_loop import AgentLoop
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
    """Deterministic LLM used for agent workflow tests."""

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


def init_git_repo(
    path: Path,
) -> None:
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
            "user.name",
            "Jimmy Test",
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
            "user.email",
            "jimmy@example.com",
        ],
        cwd=path,
        capture_output=True,
        text=True,
        check=True,
    )


def create_initial_commit(
    path: Path,
) -> None:
    subprocess.run(
        [
            "git",
            "add",
            ".",
        ],
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
    *,
    paths: list[str] | None = None,
    mode: str = "each",
    message: str | None = None,
) -> LLMResponse:
    arguments: dict[str, object] = {
        "paths": paths,
        "mode": mode,
    }

    if message is not None:
        arguments["message"] = message

    call = ToolCall(
        id=call_id,
        name="git_commit",
        arguments=arguments,
    )

    if paths is None:
        paths_json = "null"
    else:
        quoted = ",".join(f'"{path}"' for path in paths)
        paths_json = f"[{quoted}]"

    message_json = "null" if message is None else f'"{message}"'

    arguments_json = f'{{"paths":{paths_json},"mode":"{mode}","message":{message_json}}}'

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
                        "arguments": arguments_json,
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


def git_status(
    path: Path,
) -> str:
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


def git_log(
    path: Path,
) -> str:
    result = subprocess.run(
        [
            "git",
            "log",
            "-1",
            "--format=%s",
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
            # 1. Edit the file.
            edit_tool_call(),
            # 2. Commit the edited file.
            # git_commit finishes the task itself.
            git_commit_tool_call(
                paths=["example.txt"],
                mode="each",
            ),
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

    # The file was really edited.
    assert (
        file.read_text(
            encoding="utf-8",
        )
        == "hello Jimmy\n"
    )

    # The commit tool should have completed the task,
    # so the final result comes directly from the tool.
    assert "Created 1 commit(s):" in result

    # Exactly two LLM responses were needed:
    # edit_file -> git_commit -> done.
    assert llm.index == 2

    # A real commit exists.
    latest_commit = git_log(tmp_path)

    assert latest_commit
    assert latest_commit != "initial"

    # The edited file is clean.
    assert git_status(tmp_path) == ""


def test_commit_only_requested_file(
    tmp_path: Path,
) -> None:
    init_git_repo(tmp_path)

    main_file = tmp_path / "main.py"
    other_file = tmp_path / "other.py"

    main_file.write_text(
        "print('main')\n",
        encoding="utf-8",
    )

    other_file.write_text(
        "print('other')\n",
        encoding="utf-8",
    )

    create_initial_commit(tmp_path)

    main_file.write_text(
        "print('changed main')\n",
        encoding="utf-8",
    )

    other_file.write_text(
        "print('changed other')\n",
        encoding="utf-8",
    )

    git_state = GitState(tmp_path)

    llm = FakeLLM(
        [
            git_commit_tool_call(
                paths=["main.py"],
                mode="each",
            ),
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

    result = agent.run("Commit main.py.")

    assert "Created 1 commit(s):" in result

    assert llm.index == 1

    # main.py was committed.
    main_status = subprocess.run(
        [
            "git",
            "status",
            "--short",
            "--",
            "main.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert main_status.stdout.strip() == ""

    # other.py must remain uncommitted.
    other_status = subprocess.run(
        [
            "git",
            "status",
            "--short",
            "--",
            "other.py",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert other_status.stdout.strip() == "M other.py"

    # The commit must contain main.py.
    show = subprocess.run(
        [
            "git",
            "show",
            "--stat",
            "--oneline",
            "HEAD",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )

    assert "main.py" in show.stdout
    assert "other.py" not in show.stdout


def test_new_session_does_not_reuse_previous_chat(
    tmp_path: Path,
) -> None:
    llm = FakeLLM(
        [
            final_response("first"),
            final_response("second"),
        ]
    )

    tools = create_default_registry(
        root=tmp_path,
        llm=None,
    )

    from jimmy.session.json_store import JsonSessionStore

    store = JsonSessionStore(tmp_path)

    agent = AgentLoop(
        llm=llm,
        tools=tools,
        workspace=tmp_path,
        session_store=store,
        max_turns=5,
    )

    first = agent.run("First task.")

    assert first == "first"

    first_session = agent.current_session_id

    assert first_session is not None

    second = agent.run("Second task.")

    assert second == "second"

    second_session = agent.current_session_id

    assert second_session is not None

    assert first_session != second_session
