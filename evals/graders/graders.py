from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.tasks.coding_tasks import EvalTask
from evals.trace import EvalTrace

# ============================================================
# CONFIG
# ============================================================

# These tasks explicitly allow intermediate failures.
#
# E19:
#   run tests
#   if they fail -> fix
#   run tests again
#
# Therefore a failed intermediate tool call is expected.
RECOVERY_TASKS = {
    "E19",
}


# Runtime/test artifacts that should not count as meaningful
# source changes.
IGNORED_PATH_PARTS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


# ============================================================
# BASELINE
# ============================================================


@dataclass(frozen=True, slots=True)
class GitBaseline:
    """
    Git state captured immediately before Jimmy starts.

    The baseline commit lets the grader distinguish:
        - files already present in the repository
        - commits created by Jimmy during the eval
    """

    commit: str | None
    changed_files: frozenset[str]


def capture_git_state(
    workspace: Path,
) -> GitBaseline:
    """
    Capture the Git state before Jimmy runs.

    This function is part of the runner/grader contract.
    Keep it available because evals/runner.py imports it.
    """

    commit_result = subprocess.run(
        [
            "git",
            "rev-parse",
            "HEAD",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )

    commit = commit_result.stdout.strip() if commit_result.returncode == 0 else None

    changed_files = git_changed_files(
        workspace,
    )

    return GitBaseline(
        commit=commit,
        changed_files=frozenset(
            changed_files,
        ),
    )


# ============================================================
# MAIN GRADER
# ============================================================


def grade_task(
    task: EvalTask,
    trace: EvalTrace,
    workspace: Path,
    baseline: GitBaseline | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Grade whether the user's requested outcome was actually achieved.

    Important rule:

        intermediate tool failure
        !=
        final task failure

    This matters for recovery tasks such as E19.
    """

    reasons: list[str] = []

    used_tools = [item.name for item in trace.tool_trace]

    all_changed = git_changed_files(
        workspace,
    )

    changed_files = filter_runtime_artifacts(
        all_changed,
    )

    # --------------------------------------------------------
    # Tool expectations
    # --------------------------------------------------------

    missing_tools = [tool for tool in task.expected_tools if tool not in used_tools]

    forbidden_tools = [tool for tool in used_tools if tool in task.forbidden_tools]

    trace.wrong_tool_attempts = len(
        forbidden_tools,
    )

    if missing_tools:
        reasons.append(
            "missing expected tools: "
            + ", ".join(
                missing_tools,
            ),
        )

    if forbidden_tools:
        reasons.append(
            "forbidden tools used: "
            + ", ".join(
                forbidden_tools,
            ),
        )

    # --------------------------------------------------------
    # Repeated calls
    # --------------------------------------------------------

    if trace.repeated_tools:
        reasons.append(
            f"{trace.repeated_tools} repeated identical tool call(s)",
        )

    # --------------------------------------------------------
    # Expected files
    # --------------------------------------------------------

    for relative in task.expected_changed_files:
        target = workspace / relative

        if not target.exists():
            reasons.append(
                f"expected file missing: {relative}",
            )

    # --------------------------------------------------------
    # Expected unmodified files
    # --------------------------------------------------------
    #
    # Do NOT blindly inspect current `git status` here.
    #
    # Some evals intentionally create dirty files before Jimmy
    # starts.
    #
    # E09:
    #
    #   main.py   -> commit
    #   other.py  -> leave alone
    #
    # other.py being dirty at the end is CORRECT.
    # --------------------------------------------------------

    if task.id not in {
        "E09",
        "E10",
    }:
        for relative in task.expected_unmodified_files:
            if relative in changed_files:
                reasons.append(
                    f"unexpectedly changed: {relative}",
                )

    # --------------------------------------------------------
    # E04
    # --------------------------------------------------------

    if task.id == "E04":
        target = workspace / "hello.txt"

        if not target.exists():
            reasons.append(
                "hello.txt was not created",
            )
        else:
            try:
                content = target.read_text(
                    encoding="utf-8",
                )
            except UnicodeDecodeError:
                reasons.append(
                    "hello.txt is not valid UTF-8 text",
                )
            else:
                if content != "hello Jimmy":
                    reasons.append(
                        "hello.txt content is wrong",
                    )

    # --------------------------------------------------------
    # E09
    # --------------------------------------------------------
    #
    # User:
    #
    #   Commit main.py only.
    #
    # Correct:
    #
    #   main.py committed
    #   other.py NOT committed
    # --------------------------------------------------------

    committed_files = git_committed_files(
        workspace=workspace,
        baseline=baseline,
    )

    if task.id == "E09":
        if "main.py" not in committed_files:
            reasons.append(
                "main.py was not committed",
            )

        if "other.py" in committed_files:
            reasons.append(
                "other.py should not have been committed",
            )

        # main.py must no longer be dirty.
        if "main.py" in changed_files:
            reasons.append(
                "main.py is still uncommitted",
            )

    # --------------------------------------------------------
    # E10
    # --------------------------------------------------------
    #
    # User:
    #
    #   Commit all changed files one by one.
    #
    # Correct:
    #
    #   a.py -> exactly 1 commit
    #   b.py -> exactly 1 commit
    #   c.py -> exactly 1 commit
    # --------------------------------------------------------

    if task.id == "E10":
        required_files = {
            "a.py",
            "b.py",
            "c.py",
        }

        commit_counts = git_commit_counts(
            workspace=workspace,
            baseline=baseline,
        )

        missing = [
            path
            for path in sorted(
                required_files,
            )
            if commit_counts.get(
                path,
                0,
            )
            == 0
        ]

        duplicates = [
            path
            for path in sorted(
                required_files,
            )
            if commit_counts.get(
                path,
                0,
            )
            > 1
        ]

        if missing:
            reasons.append(
                "files were not committed: "
                + ", ".join(
                    missing,
                ),
            )

        if duplicates:
            reasons.append(
                "files were committed more than once: "
                + ", ".join(
                    duplicates,
                ),
            )

        remaining = sorted(
            required_files & changed_files,
        )

        if remaining:
            reasons.append(
                "files remain uncommitted: "
                + ", ".join(
                    remaining,
                ),
            )

    # --------------------------------------------------------
    # Recovery task validation
    # --------------------------------------------------------
    #
    # E19 should NOT fail just because an earlier test command
    # failed.
    #
    # Instead we verify that:
    #
    #   1. Jimmy actually attempted testing
    #   2. the requested source was changed
    #   3. the final test attempt succeeded
    # --------------------------------------------------------

    if task.id == "E19":
        test_attempts = [
            item
            for item in trace.tool_trace
            if item.name == "run_shell"
            and _looks_like_test_command(
                item.arguments.get(
                    "command",
                    "",
                ),
            )
        ]

        if not test_attempts:
            reasons.append(
                "no test command was executed",
            )
        else:
            final_test = test_attempts[-1]

            if not final_test.success:
                reasons.append(
                    "final test command failed",
                )

        expected_source = "math_utils.py"

        if expected_source not in changed_files:
            reasons.append(
                f"{expected_source} was not fixed",
            )

    # --------------------------------------------------------
    # Generic explicit verification
    # --------------------------------------------------------

    # Some tasks may define a dedicated verification command.
    #
    # For recovery tasks, E19 is handled above because its own
    # final successful test run is part of the agent trace.
    if task.test_command and task.id not in RECOVERY_TASKS:
        result = subprocess.run(
            task.test_command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

        if result.returncode != 0:
            reasons.append(
                f"final verification failed: {result.returncode}",
            )

    # --------------------------------------------------------
    # Final trace data
    # --------------------------------------------------------

    trace.changed_files = sorted(
        changed_files,
    )

    uncommitted_files = sorted(
        changed_files,
    )

    # --------------------------------------------------------
    # Final grade
    # --------------------------------------------------------

    passed = not reasons

    details: dict[str, Any] = {
        "passed": passed,
        "reasons": reasons,
        "used_tools": used_tools,
        "changed_files": sorted(
            changed_files,
        ),
        "committed_files": sorted(
            committed_files,
        ),
        "uncommitted_files": uncommitted_files,
    }

    return (
        passed,
        details,
    )


# ============================================================
# GIT STATUS
# ============================================================


def git_changed_files(
    workspace: Path,
) -> set[str]:
    """
    Return files currently reported by Git as changed.
    """

    result = subprocess.run(
        [
            "git",
            "status",
            "--short",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )

    if result.returncode != 0:
        return set()

    changed: set[str] = set()

    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue

        path = line[3:].strip()

        if not path:
            continue

        if " -> " in path:
            path = path.split(
                " -> ",
                1,
            )[1]

        changed.add(
            path.replace(
                "\\",
                "/",
            ),
        )

    return changed


# ============================================================
# GENERATED FILES
# ============================================================


def filter_runtime_artifacts(
    paths: set[str],
) -> set[str]:
    """
    Remove generated Python/test cache directories.

    These are execution byproducts, not meaningful source changes.
    """

    result: set[str] = set()

    for path in paths:
        normalized = path.replace(
            "\\",
            "/",
        )

        parts = Path(
            normalized,
        ).parts

        if any(part in IGNORED_PATH_PARTS for part in parts):
            continue

        result.add(
            normalized,
        )

    return result


# ============================================================
# GIT COMMITS
# ============================================================


def git_committed_files(
    workspace: Path,
    baseline: GitBaseline | None = None,
) -> set[str]:
    """
    Return files touched by Jimmy's commits.

    The baseline commit is excluded.
    """

    commits = git_commit_list(
        workspace,
    )

    if not commits:
        return set()

    baseline_commit = baseline.commit if baseline is not None else commits[0]

    files: set[str] = set()

    for commit in commits:
        if commit == baseline_commit:
            continue

        result = subprocess.run(
            [
                "git",
                "show",
                "--format=",
                "--name-only",
                "--no-renames",
                commit,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )

        if result.returncode != 0:
            continue

        for line in result.stdout.splitlines():
            path = line.strip()

            if not path:
                continue

            files.add(
                path.replace(
                    "\\",
                    "/",
                ),
            )

    return files


def git_commit_counts(
    workspace: Path,
    baseline: GitBaseline | None = None,
) -> dict[str, int]:
    """
    Count how many post-baseline commits touched each file.
    """

    commits = git_commit_list(
        workspace,
    )

    counts: dict[str, int] = {}

    if not commits:
        return counts

    baseline_commit = baseline.commit if baseline is not None else commits[0]

    for commit in commits:
        if commit == baseline_commit:
            continue

        result = subprocess.run(
            [
                "git",
                "show",
                "--format=",
                "--name-only",
                "--no-renames",
                commit,
            ],
            cwd=workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=20,
        )

        if result.returncode != 0:
            continue

        files = {
            line.strip().replace(
                "\\",
                "/",
            )
            for line in result.stdout.splitlines()
            if line.strip()
        }

        for path in files:
            counts[path] = (
                counts.get(
                    path,
                    0,
                )
                + 1
            )

    return counts


def git_commit_list(
    workspace: Path,
) -> list[str]:
    """
    Return commits from oldest to newest.
    """

    result = subprocess.run(
        [
            "git",
            "log",
            "--format=%H",
            "--reverse",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )

    if result.returncode != 0:
        return []

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


# ============================================================
# TEST COMMAND DETECTION
# ============================================================


def _looks_like_test_command(
    command: Any,
) -> bool:
    """
    Return True for common test-running commands.

    This is intentionally small. It is only used by E19 grading;
    it does not control Jimmy's behavior.
    """

    if not isinstance(
        command,
        str,
    ):
        return False

    text = command.lower().strip()

    test_tokens = (
        "pytest",
        "unittest",
        "npm test",
        "npm run test",
        "pnpm test",
        "yarn test",
        "cargo test",
        "go test",
    )

    return any(token in text for token in test_tokens)
