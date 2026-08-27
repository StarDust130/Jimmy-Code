import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jimmy.git.state import GitState
from jimmy.tools.base import Tool
from jimmy.tools.commit_message_generator import (
    CommitChange,
    CommitMessageGenerator,
)
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class GitCommitInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: list[str] | None = Field(
        default=None,
        description=(
            "Specific changed files to commit. When omitted, use all currently changed files."
        ),
    )

    mode: Literal[
        "each",
        "single",
    ] = Field(
        default="single",
        description=(
            "'each' creates one commit per selected file. "
            "'single' creates one commit containing all selected files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=(
            "Optional explicit commit message. "
            "When omitted, generate concise messages from the actual diff."
        ),
    )

    finish: bool = Field(
        default=True,
        description=(
            "True when committing is the final requested action. "
            "False when Jimmy must continue after committing."
        ),
    )


class GitCommitTool(Tool):
    """Commit selected Git changes through the dedicated Git tool."""

    def __init__(
        self,
        filesystem: Filesystem,
        message_generator: CommitMessageGenerator | None = None,
        git_state: GitState | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.message_generator = message_generator
        self.git_state = git_state

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return (
            "Commit Git changes. "
            "Use this tool instead of run_shell for git add or git commit. "
            "Use paths when the user names specific files. "
            "Use no paths when the user asks for all current changes. "
            "Use mode='each' for one commit per file. "
            "Use mode='single' for one commit containing all selected files. "
            "Generated messages must be short, meaningful, and begin with an emoji."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=True,
            timeout_seconds=30.0,
        )

    @property
    def input_model(
        self,
    ) -> type[BaseModel]:
        return GitCommitInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = GitCommitInput.model_validate(arguments)

        changed_files = self._get_changed_files()

        if args.paths:
            selected_files = self._select_requested_files(
                args.paths,
                changed_files,
            )
        else:
            selected_files = changed_files

        if not selected_files:
            return ToolResult.ok(
                output=("No Git changes to commit."),
                metadata={
                    "mode": args.mode,
                    "files": [],
                    "commits": [],
                    "task_complete": args.finish,
                },
            )

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in selected_files
        ]

        if args.mode == "each":
            result = self._commit_each(
                files=selected_files,
                changes=changes,
                message=args.message,
            )
        else:
            result = self._commit_single(
                files=selected_files,
                changes=changes,
                message=args.message,
            )

        # Generic completion flag.
        result.metadata["task_complete"] = args.finish

        return result

    def _commit_each(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        generated = self._generate_messages(changes)

        commits: list[dict[str, object]] = []

        diff_map = {change.path: change.diff for change in changes}

        for path in files:
            commit_message = message or generated.get(path) or self._fallback_message(path)

            self._stage([path])

            commit_hash = self._commit(commit_message)

            commits.append(
                {
                    "hash": commit_hash,
                    "message": commit_message,
                    "files": [path],
                }
            )

        lines = [f"Created {len(commits)} commit(s):"]

        for commit in commits:
            lines.append(f"- {commit['message']} ({commit['hash']})")

        return ToolResult.ok(
            output="\n".join(lines),
            metadata={
                "mode": "each",
                "files": files,
                "commits": commits,
            },
        )

    def _commit_single(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        self._stage(files)

        commit_message = (
            message or self._generate_single_message(changes) or self._fallback_group_message(files)
        )

        commit_hash = self._commit(commit_message)

        return ToolResult.ok(
            output=(
                f"Created commit: "
                f"{commit_message}\n"
                f"Commit: {commit_hash}\n"
                f"Files: {', '.join(files)}"
            ),
            metadata={
                "mode": "single",
                "files": files,
                "commits": [
                    {
                        "hash": commit_hash,
                        "message": commit_message,
                        "files": files,
                    }
                ],
            },
        )

    def _generate_messages(
        self,
        changes: list[CommitChange],
    ) -> dict[str, str]:
        if self.message_generator is None:
            return {}

        try:
            messages = self.message_generator.generate_per_file(changes)
        except Exception:
            return {}

        return {path: self._clean_message(message) for path, message in messages.items()}

    def _generate_single_message(
        self,
        changes: list[CommitChange],
    ) -> str:
        if self.message_generator is None:
            return ""

        try:
            messages = self.message_generator.generate_per_file(changes)
        except Exception:
            return ""

        if not messages:
            return ""

        # One concise group message.
        return self._clean_message(next(iter(messages.values())))

    @staticmethod
    def _clean_message(
        message: str,
    ) -> str:
        text = message.strip()

        if not text:
            return ""

        # Keep it one line.
        text = " ".join(text.split())

        # Remove accidental wrapping quotes.
        text = text.strip("\"'`")

        # Ensure an emoji-style prefix.
        if not text[0].isascii():
            return text

        return f"🛠️ {text}"

    def _get_diff(
        self,
        path: str,
    ) -> str:
        result = self._run_git(
            [
                "diff",
                "--no-ext-diff",
                "--no-color",
                "HEAD",
                "--",
                path,
            ]
        )

        if result.stdout:
            return result.stdout

        # Untracked file.
        result = subprocess.run(
            [
                "git",
                "diff",
                "--no-index",
                "--no-ext-diff",
                "--no-color",
                "--",
                "NUL",
                path,
            ],
            cwd=self.filesystem.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )

        return result.stdout

    def _get_changed_files(
        self,
    ) -> list[str]:
        result = self._run_git(
            [
                "status",
                "--short",
            ]
        )

        files: list[str] = []

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            path = line[3:].strip()

            if " -> " in path:
                path = path.split(
                    " -> ",
                    1,
                )[1]

            if path:
                files.append(
                    path.replace(
                        "\\",
                        "/",
                    )
                )

        return files

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        normalized = {
            path.replace(
                "\\",
                "/",
            )
            for path in changed_files
        }

        selected: list[str] = []

        for path in requested:
            resolved = self.filesystem.resolve_path(path)

            relative = resolved.relative_to(self.filesystem.root).as_posix()

            if relative not in normalized:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return selected

    def _stage(
        self,
        files: list[str],
    ) -> None:
        self._run_git(
            [
                "add",
                "--",
                *files,
            ]
        )

    def _commit(
        self,
        message: str,
    ) -> str:
        self._run_git(
            [
                "commit",
                "-m",
                message,
            ]
        )

        result = self._run_git(
            [
                "rev-parse",
                "--short",
                "HEAD",
            ]
        )

        return result.stdout.strip()

    def _run_git(
        self,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [
                "git",
                *args,
            ],
            cwd=self.filesystem.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )

        if result.returncode != 0:
            error = result.stderr.strip() or result.stdout.strip() or "Git command failed."

            raise RuntimeError(error)

        return result

    @staticmethod
    def _fallback_message(
        path: str,
    ) -> str:
        return f"🖕 update {Path(path).stem}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🖕 update {len(files)} files"
