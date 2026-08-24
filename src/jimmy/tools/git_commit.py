import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
            "Specific changed files to commit. When omitted, all currently changed files are used."
        ),
    )

    mode: Literal["each", "single"] = Field(
        default="each",
        description=(
            "Use 'each' for one commit per selected file. "
            "Use 'single' for one commit containing all selected files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=(
            "Explicit commit message. For 'single', it is the commit message. "
            "For 'each', it is reused for all commits only when explicitly given."
        ),
    )

    finish: bool = Field(
        default=True,
        description=(
            "Set true when committing is the final requested action. "
            "Set false when more work must happen after the commit."
        ),
    )


class GitCommitTool(Tool):
    """Create Git commits efficiently and produce useful commit messages."""

    def __init__(
        self,
        filesystem: Filesystem,
        message_generator: CommitMessageGenerator | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.message_generator = message_generator

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return (
            "Commit workspace changes. Use this instead of run_shell for "
            "git add or git commit. Supports one commit per file or one "
            "commit for all selected files. It can generate concise, "
            "meaningful emoji commit messages from actual Git diffs. "
            "Do not reread source files just to create commit messages."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=False,
            timeout_seconds=30,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return GitCommitInput

    def execute(self, arguments: BaseModel) -> ToolResult:
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
                output="No Git changes to commit.",
                metadata={
                    "mode": args.mode,
                    "commits": [],
                    "files": [],
                    "task_complete": args.finish,
                },
            )

        if args.mode == "single":
            result = self._commit_single(
                files=selected_files,
                message=args.message,
            )
        else:
            result = self._commit_each(
                files=selected_files,
                message=args.message,
            )

        result.metadata["task_complete"] = args.finish

        return result

    def _commit_single(
        self,
        files: list[str],
        message: str | None,
    ) -> ToolResult:
        self._stage(files)

        commit_message = message or self._generate_group_message(files)

        commit_hash = self._commit(commit_message)

        return ToolResult.ok(
            output=(
                f"Created commit: {commit_message}\n"
                f"Commit: {commit_hash}\n"
                f"Files: {', '.join(files)}"
            ),
            metadata={
                "mode": "single",
                "commits": [
                    {
                        "hash": commit_hash,
                        "message": commit_message,
                        "files": files,
                    }
                ],
            },
        )

    def _commit_each(
        self,
        files: list[str],
        message: str | None,
    ) -> ToolResult:
        generated_messages = self._generate_messages(files)

        commits: list[dict[str, object]] = []

        for path in files:
            self._stage([path])

            commit_message = message or generated_messages.get(path) or self._fallback_message(path)

            commit_hash = self._commit(commit_message)

            commits.append(
                {
                    "hash": commit_hash,
                    "message": commit_message,
                    "files": [path],
                }
            )

        lines = [
            f"Created {len(commits)} commit(s):",
        ]

        for commit in commits:
            lines.append(f"- {commit['message']} ({commit['hash']})")

        return ToolResult.ok(
            output="\n".join(lines),
            metadata={
                "mode": "each",
                "commits": commits,
            },
        )

    def _generate_messages(
        self,
        files: list[str],
    ) -> dict[str, str]:
        if self.message_generator is None:
            return {}

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in files
        ]

        try:
            return self.message_generator.generate(changes)
        except Exception:
            # Message generation is helpful, but it must never
            # prevent a requested commit from being created.
            return {}

    def _get_diff(self, path: str) -> str:
        result = self._run_git(
            [
                "diff",
                "--no-ext-diff",
                "--no-color",
                "HEAD",
                "--",
                path,
            ],
        )

        if result.stdout:
            return result.stdout

        # Untracked files do not appear in `git diff HEAD`.
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

    def _get_changed_files(self) -> list[str]:
        result = self._run_git(
            ["status", "--short"],
        )

        files: list[str] = []

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            path = line[3:].strip()

            if " -> " in path:
                path = path.split(" -> ", 1)[1]

            if path:
                files.append(path.replace("\\", "/"))

        return files

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        normalized_changed = {path.replace("\\", "/") for path in changed_files}

        selected: list[str] = []

        for path in requested:
            resolved = self.filesystem.resolve_path(path)

            relative = resolved.relative_to(
                self.filesystem.root,
            ).as_posix()

            if relative not in normalized_changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return selected

    def _stage(self, files: list[str]) -> None:
        self._run_git(
            [
                "add",
                "--",
                *files,
            ],
        )

    def _commit(self, message: str) -> str:
        self._run_git(
            [
                "commit",
                "-m",
                message,
            ],
        )

        result = self._run_git(
            [
                "rev-parse",
                "--short",
                "HEAD",
            ],
        )

        return result.stdout.strip()

    def _generate_group_message(
        self,
        files: list[str],
    ) -> str:
        if self.message_generator is None:
            return self._fallback_group_message(files)

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in files
        ]

        try:
            generated = self.message_generator.generate(changes)

            if generated:
                first_message = next(
                    iter(generated.values()),
                )

                if len(generated) == 1:
                    return first_message

            return self._fallback_group_message(files)

        except Exception:
            return self._fallback_group_message(files)

    def _run_git(
        self,
        args: list[str],
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", *args],
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
    def _fallback_message(path: str) -> str:
        return f"🔧 update {path.rsplit('/', 1)[-1]}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🛠️ update {len(files)} files"
