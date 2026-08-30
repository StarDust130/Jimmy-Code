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
            "When omitted, generate concise messages "
            "from the actual Git diff."
        ),
    )

    finish: bool = Field(
        default=True,
        description=(
            "Set true when this commit operation completes "
            "the current task. Set false when more work follows."
        ),
    )


class GitCommitTool(Tool):
    """
    Create Git commits inside the exact requested scope.

    The model decides the requested scope through structured
    arguments. This tool is the authority that enforces it.

    Guarantees:

    - only requested changed files are selected
    - paths must stay inside the workspace
    - only selected files are staged
    - only selected files are committed
    - unrelated staged changes are not included
    - selected files must be clean after commit
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
            "Create Git commits. Use this instead of run_shell "
            "for git add or git commit. "
            "Set paths to commit specific changed files; "
            "omit paths to commit all currently changed files. "
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
    def input_model(self) -> type[BaseModel]:
        return GitCommitInput

    # =========================================================
    # EXECUTE
    # =========================================================

    def execute(
        self,
        arguments: BaseModel,
    ) -> ToolResult:
        args = GitCommitInput.model_validate(
            arguments,
        )

        changed_files = self._get_changed_files()

        selected_files = self._resolve_scope(
            paths=args.paths,
            changed_files=changed_files,
        )

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

        # Capture the status before touching staging.
        before_status = self._status_map()

        # Generate messages from real diffs.
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

        # The tool itself owns the final scope check.
        self._verify_scope(
            requested_files=selected_files,
            before_status=before_status,
        )

        result.metadata["task_complete"] = args.finish
        result.metadata["requested_files"] = list(
            selected_files,
        )

        return result

    # =========================================================
    # SCOPE
    # =========================================================

    def _resolve_scope(
        self,
        paths: list[str] | None,
        changed_files: list[str],
    ) -> list[str]:
        """
        Resolve the exact commit scope.

        None:
            all currently changed files

        list[str]:
            exactly those changed files
        """

        normalized_changed = {self._normalize_git_path(path) for path in changed_files}

        if paths is None:
            return sorted(
                normalized_changed,
            )

        selected: list[str] = []

        for raw_path in paths:
            relative = self._normalize_requested_path(
                raw_path,
            )

            if relative not in normalized_changed:
                raise ValueError(
                    f"File is not currently changed: {relative}",
                )

            selected.append(
                relative,
            )

        # Preserve caller order while removing duplicates.
        return list(
            dict.fromkeys(selected),
        )

    def _normalize_requested_path(
        self,
        raw_path: str,
    ) -> str:
        if not isinstance(
            raw_path,
            str,
        ):
            raise TypeError(
                "Git commit paths must be strings.",
            )

        value = raw_path.strip()

        if not value:
            raise ValueError(
                "Git commit path cannot be empty.",
            )

        candidate = self.filesystem.resolve_path(
            value,
        )

        relative = candidate.relative_to(
            self.filesystem.root,
        ).as_posix()

        return relative

    @staticmethod
    def _normalize_git_path(
        path: str,
    ) -> str:
        return path.replace(
            "\\",
            "/",
        ).strip()

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
    # EACH FILE
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

            commit_message = message or generated_messages.get(path) or self._fallback_message(path)

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
            result = self.message_generator.generate(
                changes,
            )

            return {
                path: message.strip()
                for path, message in result.items()
                if isinstance(message, str) and message.strip()
            }

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

            if len(generated) == 1 and generated:
                return next(iter(generated.values())).strip()

        except Exception:
            pass

        return self._fallback_group_message(
            files,
        )

    # =========================================================
    # GIT STATUS
    # =========================================================

    def _get_changed_files(
        self,
    ) -> list[str]:
        result = self._run_git(
            [
                "status",
                "--short",
            ],
        )

        files: list[str] = []

        for line in result.stdout.splitlines():
            line = line.rstrip()

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
                    self._normalize_git_path(
                        path,
                    ),
                )

        return list(
            dict.fromkeys(files),
        )

    def _status_map(
        self,
    ) -> dict[str, str]:
        result = self._run_git(
            [
                "status",
                "--short",
            ],
        )

        status: dict[str, str] = {}

        for line in result.stdout.splitlines():
            if len(line) < 4:
                continue

            state = line[:2]
            path = line[3:].strip()

            if " -> " in path:
                path = path.split(
                    " -> ",
                    1,
                )[1]

            normalized = self._normalize_git_path(
                path,
            )

            if normalized:
                status[normalized] = state

        return status

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
    # STAGE
    # =========================================================

    def _stage(
        self,
        files: list[str],
    ) -> None:
        if not files:
            return

        self._run_git(
            [
                "add",
                "--",
                *files,
            ],
        )

    # =========================================================
    # COMMIT
    # =========================================================

    def _commit_only(
        self,
        message: str,
        files: list[str],
    ) -> str:
        """
        Commit ONLY the supplied files.

        `--only` is important because it prevents unrelated
        staged files from accidentally entering this commit.
        """

        if not files:
            raise ValueError(
                "Cannot create a commit without files.",
            )

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
            raise RuntimeError(
                "Git commit succeeded but no commit hash was returned.",
            )

        return commit_hash

    # =========================================================
    # VERIFY SELECTED FILES
    # =========================================================

    def _verify_clean(
        self,
        files: list[str],
    ) -> None:
        if not files:
            return

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
            raise RuntimeError(
                result.stderr.strip() or "Unable to verify Git status.",
            )

        if result.stdout.strip():
            raise RuntimeError(
                "Git commit completed, but selected "
                "file(s) are still changed:\n" + result.stdout.strip(),
            )

    # =========================================================
    # VERIFY SCOPE
    # =========================================================

    def _verify_scope(
        self,
        requested_files: list[str],
        before_status: dict[str, str],
    ) -> None:
        """
        Final safety check.

        Every requested file must now be clean.

        We intentionally do NOT require the entire repository
        to be clean because unrelated/pre-existing changes are
        allowed to remain untouched.
        """

        self._verify_clean(
            requested_files,
        )

        after_status = self._status_map()

        requested_set = set(
            requested_files,
        )

        # Nothing outside the requested scope should have changed
        # merely because this tool committed selected files.
        #
        # We compare only files that existed in the status before
        # the operation or are currently dirty.
        #
        # This catches accidental new dirty files caused by the
        # commit operation without treating pre-existing unrelated
        # changes as an error.
        for path in after_status:
            if path in requested_set:
                continue

            if path not in before_status:
                raise RuntimeError(
                    f"Git scope violation: unexpected file became changed: {path}",
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
        return f"🖕 update {Path(path).stem}"

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🖕 update {len(files)} files"
