from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ------------------------------------------------------------
# PACKAGE IMPORT FIX
# ------------------------------------------------------------
#
# This allows BOTH:
#
#     uv run python evals/runner.py
#
# and:
#
#     uv run python -m evals.runner
#
# to work correctly.
#
# When executed directly, Python starts with evals/ on sys.path,
# so the repository root is added before importing evals.*.
# ------------------------------------------------------------

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parent.parent

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


from evals.config import EvalConfig
from evals.graders.graders import (
    GitStateSnapshot,
    capture_git_state,
    grade_task,
)
from evals.rate_limit import (
    RateLimitedProvider,
    RequestLimiter,
)
from evals.tasks.coding_tasks import (
    TASKS,
    EvalTask,
)
from evals.trace import (
    EvalTrace,
    TraceCollector,
)

# ------------------------------------------------------------
# Jimmy imports
# ------------------------------------------------------------

try:
    from jimmy.agent.main_loop.agent_loop import AgentLoop
except ImportError:
    from jimmy.agent.agent_loop import AgentLoop

from jimmy.llm.gemini import GeminiProvider
from jimmy.permissions.manager import (
    PermissionManager,
    PermissionMode,
)
from jimmy.tools.defaults import create_default_registry

# ============================================================
# CLI
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=("Run Jimmy coding evaluations in isolated temporary workspaces."),
    )

    parser.add_argument(
        "--task",
        help="Run one eval, for example E07.",
    )

    parser.add_argument(
        "--start",
        help="First eval id, for example E01.",
    )

    parser.add_argument(
        "--end",
        help="Last eval id, for example E10.",
    )

    parser.add_argument(
        "--report",
        default="evals/traces/latest.json",
        help="Path for the JSON report.",
    )

    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help=("Keep temporary eval workspaces so they can be inspected after the run."),
    )

    return parser.parse_args()


# ============================================================
# COMMAND HELPERS
# ============================================================


def run_cmd(
    cwd: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """
    Run a command and require success.

    Used by the eval harness itself, not by Jimmy.
    """

    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


# ============================================================
# GIT FIXTURE
# ============================================================


def init_git_repo(
    workspace: Path,
) -> None:
    """Initialize an isolated Git repository."""

    run_cmd(
        workspace,
        ["git", "init"],
    )

    run_cmd(
        workspace,
        [
            "git",
            "config",
            "user.name",
            "Jimmy Eval",
        ],
    )

    run_cmd(
        workspace,
        [
            "git",
            "config",
            "user.email",
            "jimmy-eval@example.com",
        ],
    )


def create_fixtures(
    workspace: Path,
    task: EvalTask,
) -> None:
    """Create the files defined by the eval fixture."""

    for relative, content in task.files.items():
        target = workspace / relative

        target.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        target.write_text(
            content,
            encoding="utf-8",
        )


def create_baseline(
    workspace: Path,
) -> None:
    """
    Commit fixture files when they exist.

    Empty eval repositories are allowed.
    """

    status_before_commit = run_cmd(
        workspace,
        [
            "git",
            "status",
            "--porcelain",
        ],
    )

    if not status_before_commit.stdout.strip():
        return

    run_cmd(
        workspace,
        [
            "git",
            "add",
            ".",
        ],
    )

    run_cmd(
        workspace,
        [
            "git",
            "commit",
            "-m",
            "✨ eval baseline",
        ],
    )


def prepare_post_baseline_changes(
    workspace: Path,
    task: EvalTask,
) -> None:
    """
    Create intentionally dirty files AFTER the baseline.

    These are used by Git-scope tests.
    """

    if task.id not in {"E09", "E10"}:
        return

    for relative in task.files:
        path = workspace / relative

        original = path.read_text(
            encoding="utf-8",
        )

        path.write_text(
            original + "# changed by eval\n",
            encoding="utf-8",
        )


# ============================================================
# PROVIDER
# ============================================================


def make_provider(
    config: EvalConfig,
) -> tuple[Any, RequestLimiter]:
    """
    Build Gemini + shared request limiter.

    The limiter protects the entire eval run rather than
    each individual task independently.
    """

    api_key = os.getenv(
        "GEMINI_API_KEY",
    )

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Export it before running evals.")

    model = os.getenv(
        "JIMMY_EVAL_MODEL",
        "gemini-3.5-flash-lite",
    )

    provider = GeminiProvider(
        api_key=api_key,
        model=model,
    )

    limiter = RequestLimiter(
        requests_per_minute=(config.requests_per_minute),
        window_seconds=(config.request_window_seconds),
    )

    wrapped_provider = RateLimitedProvider(
        provider=provider,
        limiter=limiter,
        max_rate_limit_retries=(config.max_rate_limit_retries),
    )

    return (
        wrapped_provider,
        limiter,
    )


# ============================================================
# JIMMY
# ============================================================


def build_agent(
    workspace: Path,
    config: EvalConfig,
    provider: Any,
) -> AgentLoop:
    """Construct the real Jimmy agent."""

    tools = create_default_registry(
        root=workspace,
        llm=None,
    )

    permissions = PermissionManager(
        mode=PermissionMode.FULL_ACCESS,
    )

    return AgentLoop(
        llm=provider,
        tools=tools,
        workspace=workspace,
        max_turns=config.max_turns,
        permission_manager=permissions,
    )


# ============================================================
# TASK SELECTION
# ============================================================


def select_tasks(
    args: argparse.Namespace,
) -> list[EvalTask]:
    """Resolve --task or --start/--end."""

    if args.task:
        task_id = args.task.upper()

        for task in TASKS:
            if task.id == task_id:
                return [task]

        raise ValueError(f"Unknown eval task: {args.task}")

    ids = [task.id for task in TASKS]

    start_index = 0

    if args.start:
        start_id = args.start.upper()

        if start_id not in ids:
            raise ValueError(f"Unknown --start eval: {args.start}")

        start_index = ids.index(
            start_id,
        )

    end_index = len(TASKS) - 1

    if args.end:
        end_id = args.end.upper()

        if end_id not in ids:
            raise ValueError(f"Unknown --end eval: {args.end}")

        end_index = ids.index(
            end_id,
        )

    if end_index < start_index:
        raise ValueError("--end must be after --start.")

    return list(TASKS[start_index : end_index + 1])


# ============================================================
# ONE EVAL TASK
# ============================================================


def run_task(
    task: EvalTask,
    config: EvalConfig,
    provider: Any,
    limiter: RequestLimiter,
    keep_workspace: bool,
) -> tuple[
    EvalTrace,
    dict[str, Any],
]:
    """
    Run one task inside a disposable repository.

    Lifecycle:

        create temp workspace
        ↓
        git init
        ↓
        fixture files
        ↓
        baseline commit
        ↓
        intentional post-baseline changes
        ↓
        CAPTURE BASELINE
        ↓
        run real Jimmy
        ↓
        grade final state
        ↓
        delete workspace
    """

    workspace = Path(
        tempfile.mkdtemp(
            prefix=(f"jimmy-eval-{task.id.lower()}-"),
        )
    )

    collector = TraceCollector(
        eval_id=task.id,
        task=task.prompt,
        workspace=workspace,
    )

    try:
        # ----------------------------------------------------
        # Prepare isolated workspace
        # ----------------------------------------------------

        init_git_repo(
            workspace,
        )

        create_fixtures(
            workspace,
            task,
        )

        create_baseline(
            workspace,
        )

        prepare_post_baseline_changes(
            workspace,
            task,
        )

        # ----------------------------------------------------
        # IMPORTANT:
        # Capture baseline AFTER all fixture preparation
        # and AFTER intentional dirty state is created.
        #
        # Jimmy sees this exact state.
        # ----------------------------------------------------

        baseline: GitStateSnapshot = capture_git_state(
            workspace,
        )

        # ----------------------------------------------------
        # Build real Jimmy
        # ----------------------------------------------------

        agent = build_agent(
            workspace=workspace,
            config=config,
            provider=provider,
        )

        started = time.monotonic()

        # Record limiter counters BEFORE this task.
        # This lets us report waits caused by THIS task,
        # rather than repeating the global total.
        waits_before = limiter.wait_count
        wait_seconds_before = limiter.wait_seconds

        # ----------------------------------------------------
        # Execute task
        # ----------------------------------------------------

        try:
            result = agent.run(
                task.prompt,
                on_event=collector.on_event,
            )

        except KeyboardInterrupt:
            raise

        except Exception as exc:
            collector.fail(
                exc,
            )
            result = ""

        collector.finish(
            result,
        )

        # ----------------------------------------------------
        # Grade
        # ----------------------------------------------------

        passed, details = grade_task(
            task=task,
            trace=collector.trace,
            workspace=workspace,
            baseline=baseline,
        )

        collector.trace.passed = passed

        # ----------------------------------------------------
        # Per-task timing / rate-limit data
        # ----------------------------------------------------

        details["wall_seconds"] = time.monotonic() - started

        details["rate_limit_waits"] = limiter.wait_count - waits_before

        details["rate_limit_wait_seconds"] = limiter.wait_seconds - wait_seconds_before

        details["workspace"] = str(workspace)

        return (
            collector.trace,
            details,
        )

    except Exception as exc:
        # A harness failure is NOT a Jimmy task failure.
        # We keep the distinction explicit.
        collector.fail(
            exc,
        )

        collector.finish(
            "",
        )

        collector.trace.passed = False

        return (
            collector.trace,
            {
                "passed": False,
                "harness_error": (f"{type(exc).__name__}: {exc}"),
                "reasons": ["Eval harness failed before a reliable grade could be produced."],
                "workspace": str(workspace),
            },
        )

    finally:
        if not keep_workspace:
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )


# ============================================================
# REPORT HELPERS
# ============================================================


def print_task_result(
    index: int,
    total: int,
    task: EvalTask,
    trace: EvalTrace,
    grade: dict[str, Any],
) -> None:
    """Print one human-readable task result."""

    status = "✅ PASS" if trace.passed else "❌ FAIL"

    print(f"[{index:02d}/{total:02d}] {task.id} {status}")

    print(f"    {task.prompt}")

    print(
        f"    ⏱ {trace.elapsed_seconds:.1f}s   🧠 turns={trace.turns}   🛠 tools={trace.tool_calls}"
    )

    print(
        f"    ❌ tool failures="
        f"{trace.failed_tools}"
        f"   🔁 repeats="
        f"{trace.repeated_tools}"
        f"   🚫 wrong tools="
        f"{trace.wrong_tool_attempts}"
    )

    task_waits = int(
        grade.get(
            "rate_limit_waits",
            0,
        )
        or 0
    )

    task_wait_seconds = float(
        grade.get(
            "rate_limit_wait_seconds",
            0.0,
        )
        or 0.0
    )

    if task_waits:
        print(f"    ⏳ rate-limit waits={task_waits} ({task_wait_seconds:.1f}s)")

    changed = grade.get(
        "changed_files",
        [],
    )

    committed = grade.get(
        "committed_files",
        [],
    )

    if changed:
        print("    📁 changed: " + ", ".join(changed))

    if committed:
        print("    📦 committed: " + ", ".join(committed))

    reasons = grade.get(
        "reasons",
        [],
    )

    for reason in reasons:
        print(f"    → {reason}")

    harness_error = grade.get(
        "harness_error",
    )

    if harness_error:
        print(f"    ⚠️ HARNESS ERROR: {harness_error}")

    print()


def build_summary(
    results: list[dict[str, Any]],
    limiter: RequestLimiter,
) -> dict[str, Any]:
    """Build aggregate report data."""

    total = len(results)

    passed = sum(1 for item in results if item["trace"]["passed"])

    failed = total - passed

    avg_turns = sum(item["trace"]["turns"] for item in results) / total if total else 0.0

    avg_tools = sum(item["trace"]["tool_calls"] for item in results) / total if total else 0.0

    avg_seconds = (
        sum(item["trace"]["elapsed_seconds"] for item in results) / total if total else 0.0
    )

    total_tool_failures = sum(item["trace"]["failed_tools"] for item in results)

    total_wrong_tools = sum(item["trace"]["wrong_tool_attempts"] for item in results)

    total_repeats = sum(item["trace"]["repeated_tools"] for item in results)

    task_rate_waits = sum(
        int(
            item["grade"].get(
                "rate_limit_waits",
                0,
            )
            or 0
        )
        for item in results
    )

    task_rate_wait_seconds = sum(
        float(
            item["grade"].get(
                "rate_limit_wait_seconds",
                0.0,
            )
            or 0.0
        )
        for item in results
    )

    return {
        "tasks": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / total if total else 0.0),
        "avg_turns": avg_turns,
        "avg_tool_calls": avg_tools,
        "avg_seconds": avg_seconds,
        "total_tool_failures": (total_tool_failures),
        "total_wrong_tools": (total_wrong_tools),
        "total_repeated_tools": (total_repeats),
        "rate_limit_waits": (task_rate_waits),
        "rate_limit_wait_seconds": (task_rate_wait_seconds),
        # Global limiter totals are useful for diagnostics.
        "limiter_waits_total": (limiter.wait_count),
        "limiter_wait_seconds_total": (limiter.wait_seconds),
    }


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    args = parse_args()

    config = EvalConfig(
        keep_workspaces=(args.keep_workspaces),
    )

    tasks = select_tasks(
        args,
    )

    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║             JIMMY EVAL HARNESS              ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(f"🧪 Tasks: {len(tasks)}")

    print(f"🚦 Request limit: {config.requests_per_minute} req/min")

    print("📦 Workspace: fresh temporary Git repo per task")

    print("🔐 Jimmy mode: FULL_ACCESS")

    print("🔁 Execution: sequential")

    print()

    # --------------------------------------------------------
    # Provider
    # --------------------------------------------------------

    provider, limiter = make_provider(
        config,
    )

    results: list[dict[str, Any]] = []

    # --------------------------------------------------------
    # Execute tasks
    # --------------------------------------------------------

    for index, task in enumerate(
        tasks,
        start=1,
    ):
        trace, grade = run_task(
            task=task,
            config=config,
            provider=provider,
            limiter=limiter,
            keep_workspace=(args.keep_workspaces),
        )

        results.append(
            {
                "trace": trace.to_dict(),
                "grade": grade,
            }
        )

        print_task_result(
            index=index,
            total=len(tasks),
            task=task,
            trace=trace,
            grade=grade,
        )

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    summary = build_summary(
        results=results,
        limiter=limiter,
    )

    report = {
        "summary": summary,
        "results": results,
    }

    report_path = Path(
        args.report,
    )

    report_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Final human-readable output
    # --------------------------------------------------------

    print("╔══════════════════════════════════════════════╗")
    print("║                 FINAL RESULT                ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(f"✅ Passed: {summary['passed']}/{summary['tasks']}")

    print(f"📊 Pass rate: {summary['pass_rate']:.1%}")

    print(f"🧠 Avg turns: {summary['avg_turns']:.2f}")

    print(f"🛠 Avg tools: {summary['avg_tool_calls']:.2f}")

    print(f"⏱ Avg task time: {summary['avg_seconds']:.1f}s")

    print(f"❌ Tool failures: {summary['total_tool_failures']}")

    print(f"🚫 Wrong-tool attempts: {summary['total_wrong_tools']}")

    print(f"🔁 Repeated calls: {summary['total_repeated_tools']}")

    print(f"⏳ Rate-limit waits: {summary['rate_limit_waits']}")

    print(f"⏳ Rate-limit wait time: {summary['rate_limit_wait_seconds']:.1f}s")

    print()

    print(f"📄 Report: {report_path}")

    print()

    # --------------------------------------------------------
    # Process exit code
    # --------------------------------------------------------

    # A failed eval suite should return non-zero so CI can
    # detect a regression.
    if summary["failed"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
