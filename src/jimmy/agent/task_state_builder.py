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

_NAMED_DIRECTORY_PATTERN = re.compile(
    r"""
    \b(?:create|make|add)\s+(?:a\s+)?(?:folder|directory)\s+
    (?:called|named)?\s*
    ([A-Za-z0-9_.-]+)
    """,
    flags=re.IGNORECASE | re.VERBOSE,
)

_DIRECTORY_NAME_FIRST_PATTERN = re.compile(
    r"\b(?:create|make|add)\s+(?:a\s+|the\s+)?([A-Za-z0-9_.-]+)\s+(?:folder|directory)\b",
    flags=re.IGNORECASE,
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
        static_frontend=_is_static_frontend_task(normalized_task),
        shell_requested=_mentions_shell_work(normalized_task),
    )


def _mentions_commit(
    task: str,
) -> bool:
    if re.search(
        r"\b(?:do\s+not|don't|never|without)\s+(?:commit|committing)\b",
        task,
        flags=re.IGNORECASE,
    ):
        return False

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
    named_directories = {
        TaskState.normalize_path(match.group(1))
        for match in _NAMED_DIRECTORY_PATTERN.finditer(task)
    }
    named_directories.update(
        TaskState.normalize_path(match.group(1))
        for match in _DIRECTORY_NAME_FIRST_PATTERN.finditer(task)
    )
    named_directories = {
        candidate
        for candidate in named_directories
        if candidate and candidate.lower() not in _IGNORED_WORDS
    }
    named_directories.discard("")

    # "Create folder X; work only inside it" is a real boundary.  In this
    # form URLs and route examples elsewhere in the request must not become
    # competing filesystem scopes.
    if named_directories and re.search(
        r"(?:\b(?:inside|within)\s+(?:that|the|it)\b.{0,80}\b(?:only|not\s+outside)\b|\bwork\s+only\s+(?:inside|within)\b|\bnot\s+outside\b)",
        task,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        return named_directories

    # Remove full URLs before path extraction.  A URL has multiple slash
    # separated segments, so filtering only its hostname would still leave
    # fragments such as "events/public" behind as bogus workspace paths.
    task_without_urls = re.sub(r"https?://[^\s)]+", "", task, flags=re.IGNORECASE)

    for match in _PATH_PATTERN.finditer(task_without_urls):
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

        # Paths embedded in URLs (api.github.com/users, YOUR-DOMAIN.com/graph)
        # are API examples, not workspace paths.  Treating them as file scope
        # can reject the folder the user explicitly asked us to create.
        if any(
            "." in component
            and component.lower().split(".")[-1] in {"com", "org", "net", "dev", "io", "ai", "app"}
            for component in candidate.split("/")
        ):
            continue

        # Ordinary words are not paths.
        if "/" not in candidate and "." not in candidate:
            continue

        # A lone trailing "." or ".." is never a useful task path.
        if candidate in {".", ".."}:
            continue

        paths.add(candidate)

    # Folder names in natural language ("create a folder called webapp")
    # are an explicit scope just like "webapp/".  Retaining them prevents a
    # new subproject from being confused with the parent repository.
    for candidate in named_directories:
        if candidate.lower() not in _IGNORED_WORDS:
            paths.add(candidate)

    return paths


def _mentions_shell_work(task: str) -> bool:
    return bool(
        re.search(
            r"\b(?:run\s+(?:a\s+)?command|run\s+shell|run\s+(?:the\s+)?tests?\b|run\s+the\s+test\s+suite\b|execute\s+(?:the\s+)?tests?\b|git\s+status|current\s+git\s+status|npm|pnpm|yarn|pip|pytest|server|flask|express|curl)\b",
            task,
            flags=re.IGNORECASE,
        )
    )


def _is_static_frontend_task(task: str) -> bool:
    lower = task.lower()
    frontend_words = ("html", "css", "javascript", "static site", "browser app", "frontend")
    return any(word in lower for word in frontend_words) and not _mentions_shell_work(task)
