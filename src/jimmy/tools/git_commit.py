import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jimmy.tools.base import Tool
from jimmy.tools.filesystem import Filesystem
from jimmy.tools.models import ToolMetadata, ToolResult


class GitCommitInput(BaseModel):
    """Arguments for creating Git commits."""

    model_config = ConfigDict(extra="forbid")

    paths: list[str] | None = Field(
        default=None,
        description=(
            "Files to commit relative to the workspace. "
            "If omitted, all currently changed files are considered."
        ),
    )

    mode: Literal["each", "single"] = Field(
        default="each",
        description=(
            "Use 'each' for one commit per file, or 'single' "
            "for one commit containing all selected files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=(
            "Commit message. For 'single', this is the commit message. "
            "For 'each', this is used only when a single generic message "
            "is intentionally requested."
        ),
    )

    messages: dict[str, str] | None = Field(
        default=None,
        description=(
            "Optional per-file commit messages for mode='each'. "
            "Keys are workspace-relative file paths."
        ),
    )


class GitCommitTool(Tool):
    """Create Git commits efficiently."""

    def __init__(self, filesystem: Filesystem) -> None:
        self.filesystem = filesystem

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return (
            "Create Git commit(s) for current workspace changes. "
            "Use this instead of run_shell for git add and git commit. "
            "Supports one commit for all files or one commit per file. "
            "When no message is provided, generate a short meaningful "
            "emoji-prefixed message from the actual diff."
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
                },
            )

        if args.mode == "single":
            return self._commit_single(
                files=selected_files,
                message=args.message,
            )

        return self._commit_each(
            files=selected_files,
            message=args.message,
            messages=args.messages or {},
        )

    # ---------------------------------------------------------
    # Commit modes
    # ---------------------------------------------------------

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
        messages: dict[str, str],
    ) -> ToolResult:
        commits: list[dict[str, object]] = []

        for path in files:
            self._stage([path])

            commit_message = messages.get(path) or message or self._generate_file_message(path)

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

    # ---------------------------------------------------------
    # Git inspection
    # ---------------------------------------------------------

    def _get_changed_files(self) -> list[str]:
        result = self._run_git(["status", "--short"])

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

            relative = resolved.relative_to(self.filesystem.root).as_posix()

            if relative not in normalized_changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return selected

    # ---------------------------------------------------------
    # Staging / commit
    # ---------------------------------------------------------

    def _stage(self, files: list[str]) -> None:
        self._run_git(
            [
                "add",
                "--",
                *files,
            ]
        )

    def _commit(self, message: str) -> str:
        self._run_git(
            [
                "commit",
                "-m",
                message,
            ]
        )

        return self._get_head()

    def _get_head(self) -> str:
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

    # ---------------------------------------------------------
    # Commit message generation
    # ---------------------------------------------------------

    def _generate_file_message(self, path: str) -> str:
        diff = self._staged_diff(path)

        return self._message_from_diff(
            path=path,
            diff=diff,
        )

    def _generate_group_message(
        self,
        files: list[str],
    ) -> str:
        names = ", ".join(Path(path).stem for path in files[:3])

        if len(files) > 3:
            return f"🛠️ update {names} and related files"

        return f"🛠️ update {names}"

    def _staged_diff(self, path: str) -> str:
        result = self._run_git(
            [
                "diff",
                "--cached",
                "--unified=3",
                "--",
                path,
            ]
        )

        return result.stdout

    @staticmethod
    def _message_from_diff(
        path: str,
        diff: str,
    ) -> str:
        name = Path(path).stem.lower()
        lowered = diff.lower()

        added = [
            line
            for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        ]

        removed = [
            line
            for line in diff.splitlines()
            if line.startswith("-") and not line.startswith("---")
        ]

        added_text = "\n".join(added).lower()
        removed_text = "\n".join(removed).lower()
        diff_text = lowered

        if "test" in name or "pytest" in diff_text or "unittest" in diff_text:
            if removed and added:
                return f"🧪 update {name} tests"
            return f"🧪 add {name} tests"

        if any(
            word in diff_text
            for word in (
                "bug",
                "error",
                "exception",
                "fix",
            )
        ):
            return f"🐛 fix {name}"

        if "import " in added_text and len(added) <= 8 and len(removed) <= 8:
            return f"🔧 update {name} dependencies"

        if removed and added:
            return f"♻️ improve {name}"

        if added and not removed:
            return f"✨ add {name}"

        if removed and not added:
            return f"🧹 clean up {name}"

        return f"🔧 update {name}"
