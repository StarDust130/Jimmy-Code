from pathlib import Path

from jimmy.git.state import GitState
from jimmy.llm.base import LLMProvider
from jimmy.tools.commit_message_generator import (
    CommitMessageGenerator,
)
from jimmy.tools.create_files import CreateFilesTool
from jimmy.tools.edit_file import EditFileTool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.git_commit import GitCommitTool
from jimmy.tools.read_file import ReadFileTool
from jimmy.tools.registry import ToolRegistry
from jimmy.tools.run_shell import RunShellTool
from jimmy.tools.search_files import SearchFilesTool


def create_default_registry(
    root: Path,
    llm: LLMProvider | None = None,
    git_state: GitState | None = None,
) -> ToolRegistry:
    filesystem = Filesystem(root)

    registry = ToolRegistry()

    registry.register(ReadFileTool(filesystem))

    registry.register(SearchFilesTool(filesystem))

    registry.register(EditFileTool(filesystem))

    registry.register(RunShellTool(filesystem))

    registry.register(CreateFilesTool(filesystem))

    message_generator = CommitMessageGenerator(llm) if llm is not None else None

    registry.register(
        GitCommitTool(
            filesystem=filesystem,
            message_generator=message_generator,
            git_state=git_state,
        )
    )

    return registry
