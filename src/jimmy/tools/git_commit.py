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
            "Specific changed files to commit. When omitted, commit all currently changed files."
        ),
    )

    mode: Literal[
        "each",
        "single",
    ] = Field(
        default="each",
        description=(
            "Use 'each' for one commit per selected file. "
            "Use 'single' for one commit containing all selected files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=(
            "Optional explicit commit message. "
            "When omitted, Jimmy generates a short message "
            "from the actual diff."
        ),
    )


class GitCommitTool(Tool):
    """Create Git commits only for the requested files."""

    def __init__(
        self,
        filesystem: Filesystem,
        message_generator: (CommitMessageGenerator | None) = None,
        git_state: GitState | None = None,
    ) -> None:
        self.filesystem = filesystem
        self.message_generator = message_generator

        # Kept for compatibility with the existing
        # dependency wiring. Git itself is the source
        # of truth for the commit operation.
        self.git_state = git_state

    @property
    def name(self) -> str:
        return "git_commit"

    @property
    def description(self) -> str:
        return (
            "Commit Git changes. "
            "Always use this tool for Git commits instead of run_shell. "
            "When paths are provided, commit ONLY those files. "
            "When paths are omitted, commit all currently changed files. "
            "Use mode='each' for one commit per file. "
            "Use mode='single' for one commit containing all selected files. "
            "Generated commit messages must be short, meaningful, "
            "and start with an emoji."
        )

    @property
    def metadata(self) -> ToolMetadata:
        return ToolMetadata(
            read_only=False,
            destructive=True,
            requires_confirmation=False,
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

        if args.paths is not None:
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
                    "task_complete": True,
                },
            )

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in selected_files
        ]

        if args.mode == "single":
            return self._commit_single(
                files=selected_files,
                changes=changes,
                message=args.message,
            )

        return self._commit_each(
            files=selected_files,
            changes=changes,
            message=args.message,
        )

    # ============================================================
    # COMMIT EACH
    # ============================================================

    def _commit_each(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        messages = self._generate_per_file_messages(changes)

        commits: list[dict[str, object]] = []

        for path in files:
            commit_message = message or messages.get(path) or self._fallback_file_message(path)

            commit_message = self._normalize_commit_message(commit_message)

            # Stage ONLY this file.
            self._stage([path])

            # Commit ONLY this file.
            commit_hash = self._commit_only(
                message=commit_message,
                files=[path],
            )

            self._verify_clean([path])

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
                "commits": commits,
                "files": files,
                "task_complete": True,
            },
        )

    # ============================================================
    # COMMIT SINGLE
    # ============================================================

    def _commit_single(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        commit_message = (
            message or self._generate_group_message(changes) or self._fallback_group_message(files)
        )

        commit_message = self._normalize_commit_message(commit_message)

        # Stage only selected files.
        self._stage(files)

        # Commit only selected files.
        commit_hash = self._commit_only(
            message=commit_message,
            files=files,
        )

        self._verify_clean(files)

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
                "files": files,
                "task_complete": True,
            },
        )

    # ============================================================
    # COMMIT MESSAGE
    # ============================================================

    def _generate_per_file_messages(
        self,
        changes: list[CommitChange],
    ) -> dict[str, str]:
        if self.message_generator is None:
            return {}

        try:
            generated = self.message_generator.generate_per_file(changes)
        except Exception:
            return {}

        return {
            path: self._normalize_commit_message(message) for path, message in generated.items()
        }

    def _generate_group_message(
        self,
        changes: list[CommitChange],
    ) -> str:
        if self.message_generator is None:
            return ""

        try:
            message = self.message_generator.generate_group(changes)
        except Exception:
            return ""

        return self._normalize_commit_message(message)

    @staticmethod
    def _normalize_commit_message(
        message: str,
    ) -> str:
        text = " ".join(str(message).strip().split())

        text = text.strip("\"'`")

        if not text:
            return "📝 update changes"

        # Already starts with a non-ASCII character
        # such as an emoji.
        if not text[0].isascii():
            return text

        return f"📝 {text}"

    # ============================================================
    # FILE DISCOVERY
    # ============================================================

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

            if len(line) < 4:
                continue

            path = line[3:].strip()

            if " -> " in path:
                path = path.split(
                    " -> ",
                    1,
                )[1].strip()

            if path:
                files.append(
                    path.replace(
                        "\\",
                        "/",
                    )
                )

        return sorted(set(files))

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        changed = {
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

            if relative not in changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return list(dict.fromkeys(selected))

    # ============================================================
    # DIFF
    # ============================================================

    def _get_diff(
        self,
        path: str,
    ) -> str:
        head = subprocess.run(
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

        if head.returncode != 0:
            return self._untracked_diff(
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

        return self._untracked_diff(
            path,
            file_path,
        )

    @staticmethod
    def _untracked_diff(
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

    # ============================================================
    # GIT OPERATIONS
    # ============================================================

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

    def _commit_only(
        self,
        message: str,
        files: list[str],
    ) -> str:
        """
        Commit ONLY the supplied paths.

        This prevents unrelated staged changes from
        entering Jimmy's commit.
        """

        self._run_git(
            [
                "commit",
                "--only",
                "-m",
                message,
                "--",
                *files,
            ]
        )

        result = self._run_git(
            [
                "rev-parse",
                "--short",
                "HEAD",
            ]
        )

        commit_hash = result.stdout.strip()

        if not commit_hash:
            raise RuntimeError("Git commit succeeded but no commit hash was returned.")

        return commit_hash

    def _verify_clean(
        self,
        files: list[str],
    ) -> None:
        result = subprocess.run(
            [
                "git",
                "status",
                "--short",
                "--",
                *files,
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
            raise RuntimeError(result.stderr.strip() or "Unable to verify Git status.")

        remaining = result.stdout.strip()

        if remaining:
            raise RuntimeError(
                f"Git commit completed, but the selected file(s) are still changed:\n{remaining}"
            )

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

    # ============================================================
    # FALLBACK MESSAGES
    # ============================================================

    @staticmethod
    def _fallback_file_message(
        path: str,
    ) -> str:
        name = Path(path).stem

        if "test" in name.lower():
            return f"🧪 improve {name} tests"

        return f"🔧 update {name}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🛠️ update {len(files)} files"
