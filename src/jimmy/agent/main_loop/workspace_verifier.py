from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    """
    Immutable snapshot of one workspace file.
    """

    path: str
    exists: bool
    is_file: bool
    size: int = 0
    sha256: str | None = None


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """
    Result of real workspace verification.
    """

    verified: bool
    changed: bool
    reason: str
    paths: tuple[str, ...] = ()


class WorkspaceVerifier:
    """
    Verify that workspace mutations actually happened.

    Important:
        - Does not decide user intent.
        - Does not call the LLM.
        - Does not modify files.
        - Only verifies observable filesystem state.

    Supported mutation tools:
        edit_file
        create_files

    Git commits are verified by git_commit itself.
    Shell commands are verified by their exit code/result.
    """

    MUTATION_TOOLS = frozenset(
        {
            "edit_file",
            "create_files",
        }
    )

    def __init__(
        self,
        workspace: Path,
    ) -> None:
        self.workspace = workspace.resolve()

    # =========================================================
    # PUBLIC
    # =========================================================

    def should_verify(
        self,
        tool_name: str,
    ) -> bool:
        return tool_name in self.MUTATION_TOOLS

    def capture(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[FileSnapshot, ...]:
        """
        Capture the real filesystem state before mutation.
        """

        paths = self._paths_for_tool(
            tool_name=tool_name,
            arguments=arguments,
        )

        snapshots: list[FileSnapshot] = []

        for relative in paths:
            snapshots.append(
                self._snapshot(
                    relative,
                )
            )

        return tuple(
            snapshots,
        )

    def verify(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        before: tuple[FileSnapshot, ...],
    ) -> VerificationResult:
        """
        Compare the real filesystem state after mutation.
        """

        paths = self._paths_for_tool(
            tool_name=tool_name,
            arguments=arguments,
        )

        if not paths:
            return VerificationResult(
                verified=False,
                changed=False,
                reason=(
                    f"Cannot verify '{tool_name}': "
                    "no target path was provided."
                ),
            )

        before_map = {
            snapshot.path: snapshot
            for snapshot in before
        }

        changed_paths: list[str] = []
        failures: list[str] = []

        for relative in paths:
            previous = before_map.get(
                relative,
            )

            current = self._snapshot(
                relative,
            )

            if tool_name == "edit_file":
                self._verify_edit(
                    relative=relative,
                    before=previous,
                    after=current,
                    changed_paths=changed_paths,
                    failures=failures,
                )

            elif tool_name == "create_files":
                self._verify_create(
                    relative=relative,
                    before=previous,
                    after=current,
                    changed_paths=changed_paths,
                    failures=failures,
                )

        if failures:
            return VerificationResult(
                verified=False,
                changed=bool(changed_paths),
                reason=" ".join(failures),
                paths=tuple(paths),
            )

        return VerificationResult(
            verified=True,
            changed=bool(changed_paths),
            reason=(
                "Workspace mutation verified."
            ),
            paths=tuple(changed_paths),
        )

    # =========================================================
    # PATH EXTRACTION
    # =========================================================

    def _paths_for_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> list[str]:
        if tool_name == "edit_file":
            path = arguments.get(
                "path",
            )

            if not isinstance(
                path,
                str,
            ):
                return []

            path = path.strip()

            return [path] if path else []

        if tool_name == "create_files":
            files = arguments.get(
                "files",
                [],
            )

            if not isinstance(
                files,
                list,
            ):
                return []

            paths: list[str] = []

            for item in files:
                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                path = item.get(
                    "path",
                )

                if not isinstance(
                    path,
                    str,
                ):
                    continue

                path = path.strip()

                if path:
                    paths.append(
                        path,
                    )

            return paths

        return []

    # =========================================================
    # SNAPSHOT
    # =========================================================

    def _snapshot(
        self,
        relative_path: str,
    ) -> FileSnapshot:
        path = self._resolve(
            relative_path,
        )

        if not path.exists():
            return FileSnapshot(
                path=relative_path,
                exists=False,
                is_file=False,
            )

        if not path.is_file():
            return FileSnapshot(
                path=relative_path,
                exists=True,
                is_file=False,
            )

        data = path.read_bytes()

        return FileSnapshot(
            path=relative_path,
            exists=True,
            is_file=True,
            size=len(data),
            sha256=hashlib.sha256(
                data,
            ).hexdigest(),
        )

    # =========================================================
    # VERIFY EDIT
    # =========================================================

    @staticmethod
    def _verify_edit(
        *,
        relative: str,
        before: FileSnapshot | None,
        after: FileSnapshot,
        changed_paths: list[str],
        failures: list[str],
    ) -> None:
        if before is None:
            failures.append(
                f"Cannot verify edit of '{relative}': "
                "pre-mutation snapshot is missing."
            )
            return

        if not after.exists:
            failures.append(
                f"Edit verification failed: "
                f"'{relative}' does not exist after the edit."
            )
            return

        if not after.is_file:
            failures.append(
                f"Edit verification failed: "
                f"'{relative}' is not a file after the edit."
            )
            return

        if (
            before.sha256
            == after.sha256
        ):
            failures.append(
                f"Edit verification failed: "
                f"'{relative}' content did not change."
            )
            return

        changed_paths.append(
            relative,
        )

    # =========================================================
    # VERIFY CREATE
    # =========================================================

    @staticmethod
    def _verify_create(
        *,
        relative: str,
        before: FileSnapshot | None,
        after: FileSnapshot,
        changed_paths: list[str],
        failures: list[str],
    ) -> None:
        if before is None:
            failures.append(
                f"Cannot verify creation of '{relative}': "
                "pre-mutation snapshot is missing."
            )
            return

        if before.exists:
            failures.append(
                f"Create verification failed: "
                f"'{relative}' already existed before creation."
            )
            return

        if not after.exists:
            failures.append(
                f"Create verification failed: "
                f"'{relative}' was not created."
            )
            return

        if not after.is_file:
            failures.append(
                f"Create verification failed: "
                f"'{relative}' is not a file."
            )
            return

        changed_paths.append(
            relative,
        )

    # =========================================================
    # SAFE PATH RESOLUTION
    # =========================================================

    def _resolve(
        self,
        relative_path: str,
    ) -> Path:
        candidate = (
            self.workspace / relative_path
        ).resolve()

        try:
            candidate.relative_to(
                self.workspace,
            )
        except ValueError as exc:
            raise ValueError(
                f"Path escapes workspace: {relative_path}"
            ) from exc

        return candidate