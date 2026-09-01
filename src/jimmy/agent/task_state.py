from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class TaskState:
    """
    Small deterministic state for the current user task.

    This is NOT an LLM planner.

    It only stores facts that runtime policy can enforce.
    """

    task: str
    workspace: Path

    requested_paths: set[str] = field(
        default_factory=set,
    )

    commit_requested: bool = False

    destructive_operations_requested: bool = False

    # =========================================================
    # PATH HELPERS
    # =========================================================

    @staticmethod
    def normalize_path(
        path: str,
    ) -> str:
        """
        Normalize a workspace-relative path.
        """

        return (
            path.strip()
            .replace("\\", "/")
            .lstrip("./")
            .rstrip("/")
        )

    def is_path_in_scope(
        self,
        path: str,
    ) -> bool:
        """
        Check whether a path is allowed by the explicit task scope.

        Empty requested_paths means the user did not give an
        explicit path restriction, so do not invent one.
        """

        if not self.requested_paths:
            return True

        normalized = self.normalize_path(
            path,
        )

        if not normalized:
            return False

        for requested in self.requested_paths:
            if self._path_matches(
                normalized,
                requested,
            ):
                return True

        return False

    @classmethod
    def _path_matches(
        cls,
        path: str,
        requested: str,
    ) -> bool:
        """
        Match an exact file or a directory subtree.
        """

        path = cls.normalize_path(
            path,
        )

        requested = cls.normalize_path(
            requested,
        )

        if not path or not requested:
            return False

        if path == requested:
            return True

        return path.startswith(
            requested + "/",
        )