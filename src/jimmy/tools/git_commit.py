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
            "Specific changed files to commit. If omitted, use all current changed files."
        ),
    )

    mode: Literal["each", "single"] = Field(
        default="single",
        description=(
            "Use 'each' for one commit per selected file. "
            "Use 'single' for one commit containing all selected files."
        ),
    )

    scope: Literal["all", "jimmy", "paths"] = Field(
        default="all",
        description=(
            "all = all current changes; "
            "jimmy = only changes created during this Jimmy session; "
            "paths = only the requested files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=("Optional commit message. If omitted, Jimmy generates one from the diff."),
    )


class GitCommitTool(Tool):
    """Commit Git changes safely through one dedicated tool."""

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
            "Use this when the user asks you to commit changes. "
            "This tool handles git status, diff, staging, and commits internally. "
            "Do not use run_shell for git add or git commit when this tool can do it. "
            "Use mode='each' for one commit per file or mode='single' for one commit."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=True,
            timeout_seconds=30,
        )

    @property
    def input_model(self) -> type[BaseModel]:
        return GitCommitInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = GitCommitInput.model_validate(arguments)

        files = self._select_files(args)

        if not files:
            return ToolResult.ok(
                output="No Git changes to commit.",
                metadata={
                    "mode": args.mode,
                    "files": [],
                    "commits": [],
                },
            )

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in files
        ]

        if args.mode == "each":
            return self._commit_each(
                files=files,
                changes=changes,
                message=args.message,
            )

        return self._commit_single(
            files=files,
            changes=changes,
            message=args.message,
        )

    def _select_files(
        self,
        args: GitCommitInput,
    ) -> list[str]:
        changed_files = self._get_changed_files()

        if args.scope == "all":
            return changed_files

        if args.scope == "jimmy":
            if self.git_state is None:
                return []

            return sorted(self.git_state.jimmy_files() & set(changed_files))

        if not args.paths:
            raise ValueError("paths are required when scope='paths'.")

        return self._select_requested_files(
            args.paths,
            changed_files,
        )

    def _commit_each(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        generated_messages: dict[str, str] = {}

        if message is None and self.message_generator is not None:
            try:
                generated_messages = self.message_generator.generate_per_file(changes)
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ):
                generated_messages = {}

        commits: list[dict[str, object]] = []

        diff_map = {change.path: change.diff for change in changes}

        for path in files:
            commit_message = (
                message
                or generated_messages.get(path)
                or self._fallback_file_message(
                    path,
                    diff_map.get(path, ""),
                )
            )

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
        if message is not None:
            commit_message = message

        elif self.message_generator is not None:
            try:
                commit_message = self.message_generator.generate_group(changes)
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ):
                commit_message = self._fallback_group_message(files)

        else:
            commit_message = self._fallback_group_message(files)

        self._stage(files)

        commit_hash = self._commit(commit_message)

        return ToolResult.ok(
            output=(
                f"Created commit: {commit_message}\n"
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

    def _get_changed_files(self) -> list[str]:
        result = self._run_git(
            [
                "status",
                "--short",
            ]
        )

        files: list[str] = []

        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue

            path = line[3:].strip()

            if " -> " in path:
                path = path.split(
                    " -> ",
                    1,
                )[1]

            if path:
                files.append(path.replace("\\", "/"))

        return sorted(set(files))

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        changed = set(changed_files)
        selected: list[str] = []

        for path in requested:
            resolved = self.filesystem.resolve_path(path)

            relative = resolved.relative_to(self.filesystem.root).as_posix()

            if relative not in changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return selected

    def _get_diff(self, path: str) -> str:
        head_check = subprocess.run(
            [
                "git",
                "rev-parse",
                "--verify",
                "HEAD",
            ],
            cwd=self.filesystem.root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )

        file_path = self.filesystem.resolve_path(path)

        if head_check.returncode != 0:
            return self._untracked_file_diff(
                path,
                file_path,
            )

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

        return self._untracked_file_diff(
            path,
            file_path,
        )

    def _untracked_file_diff(
        self,
        path: str,
        file_path: Path,
    ) -> str:
        if not file_path.exists():
            return ""

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Binary file: {path}"

        lines = content.splitlines()

        return f"--- /dev/null\n+++ b/{path}\n" + "\n".join(f"+{line}" for line in lines)

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
    def _fallback_file_message(
        path: str,
        diff: str,
    ) -> str:
        filename = Path(path).stem
        text = diff.lower()

        if "--- /dev/null" in diff:
            return f"✨ add {filename}"

        if "test" in filename.lower():
            return f"🧪 improve {filename} tests"

        if "security" in text or "permission" in text:
            return f"🔐 improve {filename} security"

        if "class " in text:
            return f"♻️ refactor {filename}"

        if diff.count("\n+") > diff.count("\n-"):
            return f"✨ improve {filename}"

        return f"🔧 improve {filename}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🛠️ update {len(files)} related files"
