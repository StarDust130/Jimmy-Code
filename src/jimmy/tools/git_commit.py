from __future__ import annotations

import re
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
            "When omitted, Jimmy creates a concise message "
            "from the actual Git diff."
        ),
    )

    finish: bool = Field(
        default=True,
        description=("Set true when this commit operation completes the current task."),
    )


class GitCommitTool(Tool):
    """
    Create Git commits safely inside the requested scope.

    Commit messages follow this order:

        explicit user message
        -> LLM-generated message, when available
        -> deterministic diff-based message

    The deterministic path never produces the same generic
    message for every file.
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
            "Commit messages are short, meaningful, and "
            "based on the actual diff."
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

        # Read each diff once.
        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in selected_files
        ]

        if args.mode == "single":
            result = self._commit_single(
                files=selected_files,
                changes=changes,
                message=args.message,
            )
        else:
            result = self._commit_each(
                files=selected_files,
                changes=changes,
                message=args.message,
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

            selected.append(relative)

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
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        commit_message = self._choose_group_message(
            files=files,
            changes=changes,
            explicit_message=message,
        )

        self._stage(
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
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        generated_messages = self._generate_per_file_messages(
            changes,
        )

        diff_by_path = {change.path: change.diff for change in changes}

        commits: list[dict[str, object]] = []

        for path in files:
            commit_message = (
                message
                or generated_messages.get(path)
                or self._build_file_message(
                    path=path,
                    diff=diff_by_path.get(
                        path,
                        "",
                    ),
                )
            )

            commit_message = self._normalize_commit_message(
                commit_message,
            )

            self._stage(
                [path],
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
            "",
        ]

        for commit in commits:
            lines.append(
                f"- {commit['message']} ({commit['hash']})",
            )

        return ToolResult.ok(
            output="\n".join(
                lines,
            ),
            metadata={
                "mode": "each",
                "files": list(files),
                "commits": commits,
            },
        )

    # =========================================================
    # MESSAGE CHOICE
    # =========================================================

    def _choose_group_message(
        self,
        files: list[str],
        changes: list[CommitChange],
        explicit_message: str | None,
    ) -> str:
        if explicit_message:
            return self._normalize_commit_message(
                explicit_message,
            )

        generated = self._generate_group_message(
            changes,
        )

        if generated:
            return self._normalize_commit_message(
                generated,
            )

        return self._build_group_message(
            files=files,
            changes=changes,
        )

    # =========================================================
    # LLM MESSAGE GENERATION
    # =========================================================

    def _generate_per_file_messages(
        self,
        changes: list[CommitChange],
    ) -> dict[str, str]:
        if self.message_generator is None:
            return {}

        try:
            generated = self.message_generator.generate_per_file(
                changes,
            )
        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
        ):
            return {}

        result: dict[str, str] = {}

        for path, message in generated.items():
            if not isinstance(
                message,
                str,
            ):
                continue

            cleaned = self._normalize_commit_message(
                message,
            )

            if cleaned:
                result[path] = cleaned

        return result

    def _generate_group_message(
        self,
        changes: list[CommitChange],
    ) -> str | None:
        if self.message_generator is None:
            return None

        try:
            generated = self.message_generator.generate_group(
                changes,
            )
        except (
            RuntimeError,
            ValueError,
            TypeError,
            OSError,
            AttributeError,
        ):
            return None

        if not isinstance(
            generated,
            str,
        ):
            return None

        generated = self._normalize_commit_message(
            generated,
        )

        return generated or None

    # =========================================================
    # DETERMINISTIC MESSAGE GENERATION
    # =========================================================

    def _build_file_message(
        self,
        path: str,
        diff: str,
    ) -> str:
        """
        Generate a useful local message without another LLM call.

        The message is based on:
            - file type/name
            - added/removed content
            - common change patterns
        """

        filename = Path(
            path,
        ).name

        stem = Path(
            path,
        ).stem

        text = diff.lower()

        added_lines = self._added_lines(
            diff,
        )

        if self._looks_like_test(
            path,
            text,
        ):
            return f"🧪 update tests in {filename}"

        if self._looks_like_dependency_change(
            path,
            text,
        ):
            return f"📦 update dependencies in {filename}"

        if self._looks_like_config(
            path,
        ):
            return f"⚙️ update {stem} configuration"

        if self._looks_like_docs(
            path,
        ):
            return f"📝 update {filename} documentation"

        if self._looks_like_style(
            path,
        ):
            return f"🎨 refine styles in {filename}"

        if self._looks_like_delete(
            diff,
        ):
            return f"🗑️ remove obsolete code from {filename}"

        if self._contains_any(
            text,
            (
                "fix",
                "bug",
                "error",
                "exception",
                "broken",
            ),
        ):
            subject = (
                self._extract_subject(
                    added_lines,
                )
                or stem
            )

            return f"🐛 fix {subject}"

        if self._contains_any(
            text,
            (
                "refactor",
                "rename",
                "restructure",
                "cleanup",
                "simplify",
            ),
        ):
            subject = (
                self._extract_subject(
                    added_lines,
                )
                or stem
            )

            return f"♻️ refactor {subject}"

        if self._contains_any(
            text,
            (
                "add ",
                "added ",
                "create ",
                "created ",
                "new ",
            ),
        ):
            subject = (
                self._extract_subject(
                    added_lines,
                )
                or stem
            )

            return f"✨ add {subject}"

        if self._contains_any(
            text,
            (
                "remove ",
                "removed ",
                "delete ",
                "deleted ",
            ),
        ):
            return f"🗑️ remove code from {filename}"

        subject = (
            self._extract_subject(
                added_lines,
            )
            or stem
        )

        return f"🔧 update {subject}"

    def _build_group_message(
        self,
        files: list[str],
        changes: list[CommitChange],
    ) -> str:
        combined_diff = "\n".join(change.diff for change in changes)

        text = combined_diff.lower()

        if self._contains_any(
            text,
            (
                "fix",
                "bug",
                "error",
                "exception",
            ),
        ):
            return f"🐛 fix behavior across {len(files)} files"

        if self._contains_any(
            text,
            (
                "test",
                "assert",
                "pytest",
                "unittest",
            ),
        ):
            return f"🧪 update tests across {len(files)} files"

        if self._contains_any(
            text,
            (
                "refactor",
                "cleanup",
                "rename",
                "restructure",
            ),
        ):
            return f"♻️ refactor {len(files)} files"

        if self._contains_any(
            text,
            (
                "css",
                "style",
                "class=",
                "tailwind",
            ),
        ):
            return f"🎨 refine UI across {len(files)} files"

        return f"✨ update {self._file_summary(files)}"

    # =========================================================
    # MESSAGE HELPERS
    # =========================================================

    @staticmethod
    def _normalize_commit_message(
        message: str,
    ) -> str:
        """
        Keep Git messages on one clean line and guarantee an emoji
        at the beginning when Jimmy generated the message.
        """

        message = " ".join(
            message.strip().split(),
        )

        if not message:
            return ""

        first = message[0]

        # Common emoji ranges.
        has_emoji = ord(first) >= 0x1F000 or first in {
            "✅",
            "🐛",
            "✨",
            "🔧",
            "♻",
            "🎨",
            "🧪",
            "📝",
            "⚙",
            "📦",
            "🗑",
            "🚀",
            "🔒",
            "🚑",
        }

        if not has_emoji:
            message = f"🔧 {message}"

        return message[:120].rstrip()

    @staticmethod
    def _added_lines(
        diff: str,
    ) -> list[str]:
        lines: list[str] = []

        for line in diff.splitlines():
            if not line.startswith("+"):
                continue

            if line.startswith("+++"):
                continue

            value = line[1:].strip()

            if value:
                lines.append(
                    value,
                )

        return lines

    @staticmethod
    def _extract_subject(
        lines: list[str],
    ) -> str | None:
        for line in lines:
            function_match = re.search(
                r"\bdef\s+([A-Za-z_]\w*)",
                line,
            )

            if function_match:
                return function_match.group(1)

            class_match = re.search(
                r"\bclass\s+([A-Za-z_]\w*)",
                line,
            )

            if class_match:
                return class_match.group(1)

        return None

    @staticmethod
    def _contains_any(
        text: str,
        terms: tuple[str, ...],
    ) -> bool:
        return any(term in text for term in terms)

    @staticmethod
    def _looks_like_test(
        path: str,
        text: str,
    ) -> bool:
        filename = Path(
            path,
        ).name.lower()

        return (
            filename.startswith("test_")
            or filename.endswith("_test.py")
            or "pytest" in text
            or "unittest" in text
        )

    @staticmethod
    def _looks_like_dependency_change(
        path: str,
        text: str,
    ) -> bool:
        filename = Path(
            path,
        ).name.lower()

        return filename in {
            "pyproject.toml",
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "requirements.txt",
        } and any(
            word in text
            for word in (
                "dependencies",
                "dependency",
                "version",
                "package",
            )
        )

    @staticmethod
    def _looks_like_config(
        path: str,
    ) -> bool:
        filename = Path(
            path,
        ).name.lower()

        return filename.endswith(
            (
                ".toml",
                ".yaml",
                ".yml",
                ".ini",
            ),
        ) or filename.startswith(
            (
                ".env",
                "config",
            ),
        )

    @staticmethod
    def _looks_like_docs(
        path: str,
    ) -> bool:
        filename = Path(
            path,
        ).name.lower()

        return filename.endswith(
            (
                ".md",
                ".rst",
                ".txt",
            ),
        )

    @staticmethod
    def _looks_like_style(
        path: str,
    ) -> bool:
        suffix = Path(
            path,
        ).suffix.lower()

        return suffix in {
            ".css",
            ".scss",
            ".sass",
        }

    @staticmethod
    def _looks_like_delete(
        diff: str,
    ) -> bool:
        added = 0
        removed = 0

        for line in diff.splitlines():
            if line.startswith("+++"):
                continue

            if line.startswith("---"):
                continue

            if line.startswith("+"):
                added += 1

            elif line.startswith("-"):
                removed += 1

        return removed > 0 and added == 0

    @staticmethod
    def _file_summary(
        files: list[str],
    ) -> str:
        names = [Path(path).name for path in files]

        if len(names) == 1:
            return names[0]

        if len(names) == 2:
            return f"{names[0]} and {names[1]}"

        return f"{names[0]}, {names[1]} + {len(names) - 2} more"

    # =========================================================
    # GIT
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
            dict.fromkeys(
                files,
            ),
        )

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

        file_path = self.filesystem.resolve_path(
            path,
        )

        if head.returncode != 0:
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
            ],
        )

        if result.stdout:
            return result.stdout

        return self._untracked_file_diff(
            path,
            file_path,
        )

    @staticmethod
    def _untracked_file_diff(
        path: str,
        file_path: Path,
    ) -> str:
        if not file_path.exists():
            return ""

        try:
            content = file_path.read_text(
                encoding="utf-8",
            )
        except UnicodeDecodeError:
            return f"Binary file: {path}"

        lines = content.splitlines()

        if not lines:
            return f"--- /dev/null\n+++ b/{path}\n"

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
    # VERIFY
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
