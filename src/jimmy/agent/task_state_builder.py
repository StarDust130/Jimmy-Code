from __future__ import annotations

import re
from pathlib import Path

from jimmy.agent.task_state import TaskState


_IGNORED_WORDS = {
    "a",
    "all",
    "an",
    "and",
    "bug",
    "code",
    "commit",
    "committing",
    "committed",
    "create",
    "delete",
    "directory",
    "everything",
    "file",
    "files",
    "fix",
    "folder",
    "for",
    "in",
    "into",
    "make",
    "modify",
    "project",
    "repo",
    "repository",
    "reset",
    "restore",
    "run",
    "test",
    "tests",
    "the",
    "to",
    "with",
}


_PATH_PATTERN = re.compile(
    r"""
    (?<![A-Za-z0-9_-])
    (?:
        [A-Za-z0-9_.-]+/
    )*
    [A-Za-z0-9_.-]+
    /?
    (?![A-Za-z0-9_-])
    """,
    flags=re.VERBOSE,
)


def build_task_state(
    task: str,
    workspace: Path,
) -> TaskState:
    """
    Build small deterministic runtime facts.

    This does not plan the task or understand arbitrary language.
    """

    normalized_task = task.strip()

    if not normalized_task:
        raise ValueError(
            "Task cannot be empty.",
        )

    return TaskState(
        task=normalized_task,
        workspace=workspace.resolve(),
        requested_paths=_extract_explicit_paths(
            normalized_task,
        ),
        commit_requested=_mentions_commit(
            normalized_task,
        ),
        destructive_operations_requested=(
            _mentions_destructive_operation(
                normalized_task,
            )
        ),
    )


def _mentions_commit(
    task: str,
) -> bool:
    return bool(
        re.search(
            r"\b(?:commit|committing|committed)\b",
            task,
            flags=re.IGNORECASE,
        ),
    )


def _mentions_destructive_operation(
    task: str,
) -> bool:
    return bool(
        re.search(
            r"""
            \b
            (?:
                reset
                | restore
                | checkout
                | switch
                | clean
                | rebase
                | revert
                | cherry-pick
            )
            \b
            """,
            task,
            flags=re.IGNORECASE | re.VERBOSE,
        )
    )


def _extract_explicit_paths(
    task: str,
) -> set[str]:
    """
    Extract only obvious path-looking values.

    Examples:
        main.py
        src/main.py
        game/
        game/index.html
    """

    paths: set[str] = set()

    for match in _PATH_PATTERN.finditer(task):
        candidate = match.group(0).strip()

        # Strip normal sentence punctuation.
        candidate = candidate.rstrip(
            ".,;:!?)]}\"'",
        )

        candidate = TaskState.normalize_path(
            candidate,
        )

        if not candidate:
            continue

        if candidate.lower() in _IGNORED_WORDS:
            continue

        # Ordinary words are not paths.
        if "/" not in candidate and "." not in candidate:
            continue

        # A lone trailing "." or ".." is never a useful task path.
        if candidate in {".", ".."}:
            continue

        paths.add(candidate)

    return paths