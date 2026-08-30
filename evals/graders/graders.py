from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.tasks.coding_tasks import EvalTask
from evals.trace import EvalTrace


@dataclass(frozen=True)
class GitStateSnapshot:
    """Git state captured before an eval task starts."""

    head: str
    status_files: frozenset[str]


def capture_git_state(
    workspace: Path,
) -> GitStateSnapshot:
    """
    Capture the repository state before Jimmy starts.

    This lets graders distinguish:
        - files that were already dirty
        - files Jimmy changed
        - files Jimmy committed
    """

    head_result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )

    if head_result.returncode != 0:
        return GitStateSnapshot(
            head="",
            status_files=frozenset(),
        )

    return GitStateSnapshot(
        head=head_result.stdout.strip(),
        status_files=frozenset(
            git_status_files(workspace),
        ),
    )


def grade_task(
    task: EvalTask,
    trace: EvalTrace,
    workspace: Path,
    baseline: GitStateSnapshot | None = None,
) -> tuple[bool, dict[str, Any]]:
    """
    Grade the observable outcome of the task.

    Tool sequence is a quality signal, not the definition of correctness.

    When a Git baseline is supplied, grading distinguishes:
        - committed changes
        - uncommitted changes
        - unexpected changes
    """

    reasons: list[str] = []

    used_tools = [item.name for item in trace.tool_trace]

    # ----------------------------------------------------------
    # TOOL QUALITY
    # ----------------------------------------------------------

    missing_expected = [tool for tool in task.expected_tools if tool not in used_tools]

    wrong_tools = [tool for tool in used_tools if tool in task.forbidden_tools]

    trace.wrong_tool_attempts = len(wrong_tools)

    if missing_expected:
        reasons.append("missing expected tools: " + ", ".join(missing_expected))

    if wrong_tools:
        reasons.append("forbidden tools used: " + ", ".join(wrong_tools))

    if trace.failed_tools:
        reasons.append(f"{trace.failed_tools} tool call(s) failed")

    if trace.repeated_tools:
        reasons.append(f"{trace.repeated_tools} repeated identical tool call(s)")

    # ----------------------------------------------------------
    # GIT STATE
    # ----------------------------------------------------------

    committed_files: set[str] = set()
    uncommitted_files: set[str] = set()
    changed_files: set[str] = set()

    if baseline is not None and baseline.head:
        committed_files = git_committed_files_since(
            workspace,
            baseline.head,
        )

        uncommitted_files = git_status_files(
            workspace,
        )

        # Files changed by the task are the union of:
        # committed changes + remaining working-tree changes.
        changed_files = committed_files | uncommitted_files

    else:
        changed_files = git_changed_files(
            workspace,
        )
        uncommitted_files = set(changed_files)

    trace.changed_files = sorted(changed_files)

    # ----------------------------------------------------------
    # EXPECTED FILES
    # ----------------------------------------------------------

    for relative in task.expected_changed_files:
        if not path_exists(
            workspace,
            relative,
        ):
            reasons.append(f"expected file missing: {relative}")

    # ----------------------------------------------------------
    # UNMODIFIED FILES
    # ----------------------------------------------------------

    for relative in task.expected_unmodified_files:
        if relative in changed_files:
            reasons.append(f"unexpectedly changed: {relative}")

    # ----------------------------------------------------------
    # TASK-SPECIFIC GIT CHECKS
    # ----------------------------------------------------------

    if task.id == "E09":
        """
        Commit main.py only.

        Correct result:

            main.py
                -> committed

            other.py
                -> remains uncommitted

        The old grader incorrectly treated the remaining other.py
        modification as a failure.
        """

        if "main.py" not in committed_files:
            reasons.append("main.py was not committed")

        if "other.py" not in uncommitted_files:
            reasons.append("other.py should remain uncommitted")

        if "other.py" in committed_files:
            reasons.append("other.py was incorrectly committed")

    elif task.id == "E10":
        """
        Commit all changed files one by one.

        Every changed file must have its own commit and nothing
        should remain uncommitted.
        """

        expected_files = {path.replace("\\", "/") for path in task.files}

        missing_commits = expected_files - committed_files

        if missing_commits:
            reasons.append("files were not committed: " + ", ".join(sorted(missing_commits)))

        unexpected_commits = committed_files - expected_files

        if unexpected_commits:
            reasons.append("unexpected files committed: " + ", ".join(sorted(unexpected_commits)))

        remaining = uncommitted_files & expected_files

        if remaining:
            reasons.append("files remain uncommitted: " + ", ".join(sorted(remaining)))

        # One commit per requested file.
        commit_groups = git_commit_file_groups(
            workspace,
            baseline.head if baseline else "",
        )

        relevant_groups = [files for files in commit_groups if files & expected_files]

        per_file_commits: dict[str, int] = {path: 0 for path in expected_files}

        for commit_files in relevant_groups:
            relevant = commit_files & expected_files

            if len(relevant) != 1:
                reasons.append(
                    f"one-by-one commit requirement violated: commit contains {sorted(relevant)}"
                )
                continue

            file_path = next(iter(relevant))
            per_file_commits[file_path] += 1

        missing_one_by_one = [path for path, count in per_file_commits.items() if count != 1]

        if missing_one_by_one:
            reasons.append(
                "each requested file must have exactly one commit: "
                + ", ".join(sorted(missing_one_by_one))
            )

    # ----------------------------------------------------------
    # FILE CONTENT CHECKS
    # ----------------------------------------------------------

    if task.id == "E04":
        target = workspace / "hello.txt"

        if not target.exists():
            reasons.append("hello.txt was not created")

        elif (
            target.read_text(
                encoding="utf-8",
            )
            != "hello Jimmy"
        ):
            reasons.append("hello.txt content is wrong")

    # ----------------------------------------------------------
    # VERIFICATION COMMAND
    # ----------------------------------------------------------

    if task.test_command:
        result = subprocess.run(
            task.test_command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

        if result.returncode != 0:
            reasons.append(f"verification command failed: {result.returncode}")

    # ----------------------------------------------------------
    # FINAL RESULT
    # ----------------------------------------------------------

    passed = not reasons

    details = {
        "passed": passed,
        "reasons": reasons,
        "used_tools": used_tools,
        "changed_files": sorted(changed_files),
        "committed_files": sorted(committed_files),
        "uncommitted_files": sorted(uncommitted_files),
    }

    return passed, details


def git_status_files(
    workspace: Path,
) -> set[str]:
    """Return currently uncommitted files."""

    result = subprocess.run(
        ["git", "status", "--porcelain"],
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

    files: set[str] = set()

    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue

        path = line[3:].strip()

        if " -> " in path:
            path = path.split(
                " -> ",
                1,
            )[1]

        files.add(path.replace("\\", "/"))

    return files


def git_committed_files_since(
    workspace: Path,
    baseline_head: str,
) -> set[str]:
    """
    Return files touched by commits created after baseline.
    """

    if not baseline_head:
        return set()

    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            f"{baseline_head}..HEAD",
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

    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def git_commit_file_groups(
    workspace: Path,
    baseline_head: str,
) -> list[set[str]]:
    """
    Return the files touched by every commit after baseline.

    Example:

        commit 1 -> {"a.py"}
        commit 2 -> {"b.py"}
        commit 3 -> {"c.py"}

    This lets E10 verify true one-by-one commits.
    """

    if not baseline_head:
        return []

    log_result = subprocess.run(
        [
            "git",
            "rev-list",
            "--reverse",
            f"{baseline_head}..HEAD",
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=20,
    )

    if log_result.returncode != 0:
        return []

    groups: list[set[str]] = []

    for sha in log_result.stdout.splitlines():
        sha = sha.strip()

        if not sha:
            continue

        result = subprocess.run(
            [
                "git",
                "show",
                "--format=",
                "--name-only",
                sha,
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
            line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()
        }

        groups.append(files)

    return groups


def git_changed_files(
    workspace: Path,
) -> set[str]:
    """
    Backwards-compatible fallback when no baseline is supplied.
    """

    return git_status_files(workspace)


def path_exists(
    workspace: Path,
    relative: str,
) -> bool:
    return (workspace / relative).exists()
