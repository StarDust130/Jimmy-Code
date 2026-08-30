from __future__ import annotations

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
from jimmy.tools.models import (
    ToolMetadata,
    ToolResult,
)


class GitCommitInput(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )

    paths: list[str] | None = Field(
        default=None,
        description=(
            "Specific changed files to commit. Omit paths to commit all currently changed files."
        ),
    )

    mode: Literal[
        "each",
        "single",
    ] = Field(
        default="each",
        description=(
            "Use 'each' for one commit per selected file. "
            "Use 'single' for one commit containing all "
            "selected files."
        ),
    )

    message: str | None = Field(
        default=None,
        description=(
            "Optional explicit commit message. "
            "When omitted, generate a concise message "
            "from the actual Git diff."
        ),
    )

    finish: bool = Field(
        default=True,
        description=(
            "Set true when committing should finish the "
            "current task. Set false when more work follows."
        ),
    )


class GitCommitTool(Tool):
    """
    Create Git commits within the exact requested scope.

    The tool is authoritative about Git state.

    It never relies on natural-language parsing to determine
    which files are committed.
    """

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
            "Create Git commits. Use this instead of "
            "run_shell for git add or git commit. "
            "Set paths to commit specific changed files; "
            "omit paths to commit all current changes. "
            "Use mode='each' for one commit per file or "
            "mode='single' for one commit containing all "
            "selected files. "
            "Only the selected paths are committed."
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
    def input_model(
        self,
    ) -> type[BaseModel]:
        return GitCommitInput

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = GitCommitInput.model_validate(
            arguments,
        )

        changed_files = self._get_changed_files()

        # -----------------------------------------------------
        # Select scope from structured arguments only.
        # -----------------------------------------------------

        if args.paths is None:
            selected_files = list(
                changed_files,
            )
        else:
            selected_files = self._select_requested_files(
                requested=args.paths,
                changed_files=changed_files,
            )

        # -----------------------------------------------------
        # Nothing to commit.
        # -----------------------------------------------------

        if not selected_files:
            return ToolResult.ok(
                output="No Git changes to commit.",
                metadata={
                    "mode": args.mode,
                    "files": [],
                    "commits": [],
                    "task_complete": args.finish,
                },
            )

        # -----------------------------------------------------
        # Prepare diffs for optional message generation.
        # -----------------------------------------------------

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in selected_files
        ]

        del changes
        # The message generator below creates its own
        # CommitChange collection. Keeping this line-free
        # makes the actual commit flow easier to follow.

        # -----------------------------------------------------
        # Execute requested commit mode.
        # -----------------------------------------------------

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

    # =========================================================
    # SINGLE COMMIT
    # =========================================================

    def _commit_single(
        self,
        files: list[str],
        message: str | None,
    ) -> ToolResult:
        self._stage(
            files,
        )

        commit_message = message or self._generate_group_message(
            files,
        )

        commit_hash = self._commit_only(
            message=commit_message,
            files=files,
        )

        self._verify_clean(
            files,
        )

        return ToolResult.ok(
            output=(
                f"Created commit: {commit_message}\n"
                f"Commit: {commit_hash}\n"
                f"Files: {', '.join(files)}"
            ),
            metadata={
                "mode": "single",
                "files": list(files),
                "commits": [
                    {
                        "hash": commit_hash,
                        "message": commit_message,
                        "files": list(files),
                    }
                ],
            },
        )

    # =========================================================
    # ONE COMMIT PER FILE
    # =========================================================

    def _commit_each(
        self,
        files: list[str],
        message: str | None,
    ) -> ToolResult:
        generated_messages = self._generate_messages(
            files,
        )

        commits: list[dict[str, object]] = []

        for path in files:
            self._stage(
                [path],
            )

            commit_message = (
                message
                or generated_messages.get(
                    path,
                )
                or self._fallback_message(
                    path,
                )
            )

            commit_hash = self._commit_only(
                message=commit_message,
                files=[path],
            )

            self._verify_clean(
                [path],
            )

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
                "files": list(files),
                "commits": commits,
            },
        )

    # =========================================================
    # MESSAGE GENERATION
    # =========================================================

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
            return self.message_generator.generate(
                changes,
            )
        except Exception:
            return {}

    def _generate_group_message(
        self,
        files: list[str],
    ) -> str:
        if self.message_generator is None:
            return self._fallback_group_message(
                files,
            )

        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in files
        ]

        try:
            generated = self.message_generator.generate(
                changes,
            )

            if generated and len(generated) == 1:
                return next(iter(generated.values()))

        except Exception:
            pass

        return self._fallback_group_message(
            files,
        )

    # =========================================================
    # GIT STATE
    # =========================================================

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
                )[1]

            if path:
                files.append(
                    path.replace(
                        "\\",
                        "/",
                    )
                )

        return list(
            dict.fromkeys(
                files,
            )
        )

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        normalized_changed = {
            path.replace(
                "\\",
                "/",
            )
            for path in changed_files
        }

        selected: list[str] = []

        for requested_path in requested:
            resolved = self.filesystem.resolve_path(
                requested_path,
            )

            relative = resolved.relative_to(
                self.filesystem.root,
            ).as_posix()

            if relative not in normalized_changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(
                relative,
            )

        return list(
            dict.fromkeys(
                selected,
            )
        )

    # =========================================================
    # DIFF
    # =========================================================

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

        if head.returncode != 0:
            return self._untracked_diff(
                path,
            )

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

        return self._untracked_diff(
            path,
        )

    def _untracked_diff(
        self,
        path: str,
    ) -> str:
        file_path = self.filesystem.resolve_path(
            path,
        )

        if not file_path.exists():
            return ""

        try:
            content = file_path.read_text(
                encoding="utf-8",
            )
        except UnicodeDecodeError:
            return f"Binary file: {path}"

        lines = content.splitlines()

        return f"--- /dev/null\n+++ b/{path}\n" + "\n".join(f"+{line}" for line in lines)

    # =========================================================
    # COMMIT
    # =========================================================

    def _stage(
        self,
        files: list[str],
    ) -> None:
        self._run_git(
            [
                "add",
                "--",
                *files,
            ],
        )

    def _commit_only(
        self,
        message: str,
        files: list[str],
    ) -> str:
        """
        Commit ONLY these files.

        This is the critical Git-scope protection.

        Other files already staged in the repository
        are not included.
        """

        self._run_git(
            [
                "commit",
                "--only",
                "-m",
                message,
                "--",
                *files,
            ],
        )

        result = self._run_git(
            [
                "rev-parse",
                "--short",
                "HEAD",
            ],
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

    # =========================================================
    # PROCESS
    # =========================================================

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

            raise RuntimeError(
                error,
            )

        return result

    # =========================================================
    # FALLBACK MESSAGES
    # =========================================================

    @staticmethod
    def _fallback_message(
        path: str,
    ) -> str:
        return f"🛠️ update {Path(path).stem}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🛠️ update {len(files)} files"
