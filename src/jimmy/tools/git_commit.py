import subprocess
from pathlib import Path
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
            "Specific changed files to commit. If omitted, commit all currently changed files."
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
            "Optional explicit commit message. "
            "When omitted, Jimmy generates one from the actual diff."
        ),
    )


class GitCommitTool(Tool):
    """Create Git commits without making the main agent manage Git manually."""

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
            "Create Git commits. Always use this tool for Git commits "
            "instead of run_shell. Supports one commit per file or one "
            "commit for all selected files. When no message is supplied, "
            "generate meaningful short commit messages from the actual "
            "Git diff."
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

        # 1️⃣ Find changed files.
        changed_files = self._get_changed_files()

        # 2️⃣ Select requested files.
        if args.paths:
            selected_files = self._select_requested_files(
                args.paths,
                changed_files,
            )
        else:
            selected_files = changed_files

        # 3️⃣ Nothing to commit.
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

        # 4️⃣ Read actual diffs before staging.
        changes = [
            CommitChange(
                path=path,
                diff=self._get_diff(path),
            )
            for path in selected_files
        ]

        # 5️⃣ Create commits.
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

        return result

    # ======================================
    # 1️⃣ COMMIT EACH FILE
    # ======================================

    def _commit_each(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        generated_messages: dict[str, str] = {}

        # 🤖 Generate messages when needed.
        if message is None and self.message_generator is not None:
            try:
                generated_messages = self.message_generator.generate_per_file(
                    changes,
                )
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ):
                generated_messages = {}

        commits: list[dict[str, object]] = []

        # 🔄 Create one commit per file.
        for path in files:
            # 📦 Stage only this file.
            self._stage([path])

            commit_message = (
                message
                or generated_messages.get(path)
                or self._fallback_file_message(
                    path,
                    self._get_diff(path),
                )
            )

            # ✅ Create commit.
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
                "files": files,
                "task_complete": True,
            },
        )

    # ======================================
    # 2️⃣ COMMIT ALL TOGETHER
    # ======================================

    def _commit_single(
        self,
        files: list[str],
        changes: list[CommitChange],
        message: str | None,
    ) -> ToolResult:
        # 📦 Stage selected files.
        self._stage(files)

        # 📝 Create commit message.
        if message is not None:
            commit_message = message

        elif self.message_generator is not None:
            try:
                commit_message = self.message_generator.generate_group(
                    changes,
                )
            except (
                RuntimeError,
                ValueError,
                TypeError,
                OSError,
            ):
                commit_message = self._fallback_group_message(
                    files,
                )

        else:
            commit_message = self._fallback_group_message(
                files,
            )

        # ✅ Create commit.
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
                "files": files,
                "task_complete": True,
            },
        )

    # ======================================
    # 3️⃣ FIND CHANGED FILES
    # ======================================

    def _get_changed_files(self) -> list[str]:
        result = self._run_git(
            [
                "status",
                "--short",
            ],
        )

        files: list[str] = []

        for line in result.stdout.splitlines():
            if not line.strip():
                continue

            path = line[3:].strip()

            # 🔄 Handle renamed files.
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

        return sorted(set(files))

    # ======================================
    # 4️⃣ SELECT REQUESTED FILES
    # ======================================

    def _select_requested_files(
        self,
        requested: list[str],
        changed_files: list[str],
    ) -> list[str]:
        changed = {path.replace("\\", "/") for path in changed_files}

        selected: list[str] = []

        for path in requested:
            resolved = self.filesystem.resolve_path(path)

            relative = resolved.relative_to(self.filesystem.root).as_posix()

            if relative not in changed:
                raise ValueError(f"File is not currently changed: {relative}")

            selected.append(relative)

        return selected

    # ======================================
    # 5️⃣ GET REAL DIFF
    # ======================================

    def _get_diff(self, path: str) -> str:
        """Return the real diff, including brand-new files."""

        # 🔎 Check whether this repository already has a HEAD.
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

        # 🆕 No commits yet.
        if head_check.returncode != 0:
            return self._untracked_file_diff(
                path,
                file_path,
            )

        # 📄 Existing repository.
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

        # 🆕 Untracked file in an existing repository.
        return self._untracked_file_diff(
            path,
            file_path,
        )

    # ======================================
    # 6️⃣ BUILD UNTRACKED FILE DIFF
    # ======================================

    def _untracked_file_diff(
        self,
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

        return f"--- /dev/null\n+++ b/{path}\n" + "\n".join(f"+{line}" for line in lines)

    # ======================================
    # 7️⃣ STAGE FILES
    # ======================================

    def _stage(self, files: list[str]) -> None:
        self._run_git(
            [
                "add",
                "--",
                *files,
            ],
        )

    # ======================================
    # 8️⃣ CREATE COMMIT
    # ======================================

    def _commit(self, message: str) -> str:
        # ✅ Create the commit.
        self._run_git(
            [
                "commit",
                "-m",
                message,
            ],
        )

        # 🔎 Verify HEAD now exists.
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

        if head_check.returncode != 0:
            error = (
                head_check.stderr.strip() or "Git commit succeeded but HEAD could not be verified."
            )

            raise RuntimeError(error)

        # 🏷️ Get the short commit hash.
        result = self._run_git(
            [
                "rev-parse",
                "--short",
                "HEAD",
            ],
        )

        commit_hash = result.stdout.strip()

        if not commit_hash:
            raise RuntimeError("Git commit was created but no commit hash was returned.")

        return commit_hash

    # ======================================
    # 9️⃣ RUN GIT COMMAND
    # ======================================

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

    # ======================================
    # 🔟 FALLBACK FILE MESSAGE
    # ======================================

    @staticmethod
    def _fallback_file_message(
        path: str,
        diff: str,
    ) -> str:
        text = diff.lower()
        filename = Path(path).stem

        if "test" in filename.lower():
            return f"🧪 improve {filename} tests"

        if "security" in text or "permission" in text:
            return f"🔐 improve {filename} security"

        if "import " in text:
            return f"🔧 update {filename} integration"

        if "class " in text and "def " in text:
            return f"♻️ refactor {filename}"

        if "--- /dev/null" in diff:
            return f"✨ add {filename}"

        if diff.count("\n+") > diff.count("\n-"):
            return f"✨ improve {filename}"

        return f"🔧 improve {filename}"

    # ======================================
    # 1️⃣1️⃣ FALLBACK GROUP MESSAGE
    # ======================================

    @staticmethod
    def _fallback_group_message(
        files: list[str],
    ) -> str:
        return f"🛠️ update {len(files)} related files"
