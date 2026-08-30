from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# ============================================================
# DIRECT EXECUTION SUPPORT
# ============================================================
#
# Both work:
#
#   python evals/runner.py
#   python -m evals.runner
#
# ============================================================

if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parent.parent

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))


# ============================================================
# EVAL IMPORTS
# ============================================================

from evals.config import EvalConfig
from evals.graders.graders import (
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

# ============================================================
# JIMMY IMPORTS
# ============================================================

try:
    from jimmy.agent.main_loop.agent_loop import AgentLoop
except ImportError:
    from jimmy.agent.agent_loop import AgentLoop

from jimmy.config.settings import Settings
from jimmy.llm.gemini import GeminiProvider
from jimmy.permissions.manager import (
    PermissionManager,
    PermissionMode,
)
from jimmy.tools.defaults import create_default_registry

# ============================================================
# ARGUMENTS
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Jimmy coding evaluations.",
    )

    parser.add_argument(
        "--task",
        help="Run one eval, e.g. E07.",
    )

    parser.add_argument(
        "--start",
        help="First eval ID, e.g. E01.",
    )

    parser.add_argument(
        "--end",
        help="Last eval ID, e.g. E10.",
    )

    parser.add_argument(
        "--report",
        default="evals/traces/latest.json",
        help="JSON report path.",
    )

    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help="Keep temporary eval workspaces.",
    )

    return parser.parse_args()


# ============================================================
# COMMAND EXECUTION
# ============================================================


def run_cmd(
    cwd: Path,
    args: list[str],
    *,
    timeout: int = 30,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )

    if check and result.returncode != 0:
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        details = stderr or stdout or "Command failed without output."

        raise RuntimeError(
            f"Command failed with exit code {result.returncode}:\n$ {' '.join(args)}\n{details}",
        )

    return result


# ============================================================
# GIT WORKSPACE
# ============================================================


def init_git_repo(
    workspace: Path,
) -> None:
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
    for relative_path, content in task.files.items():
        target = workspace / relative_path

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
    Create the clean baseline commit.

    Fixtures must exist before this is called.
    """

    run_cmd(
        workspace,
        ["git", "add", "."],
    )

    status = run_cmd(
        workspace,
        [
            "git",
            "status",
            "--porcelain",
        ],
    )

    if not status.stdout.strip():
        return

    run_cmd(
        workspace,
        [
            "git",
            "commit",
            "-m",
            "eval baseline",
        ],
    )


def prepare_post_baseline_changes(
    workspace: Path,
    task: EvalTask,
) -> None:
    """
    Add intentional dirty changes for Git evals.
    """

    if task.id not in {
        "E09",
        "E10",
    }:
        return

    for relative_path in task.files:
        path = workspace / relative_path

        original = path.read_text(
            encoding="utf-8",
        )

        path.write_text(
            original + "\n# changed by eval\n",
            encoding="utf-8",
        )


# ============================================================
# GEMINI
# ============================================================


def make_provider(
    config: EvalConfig,
) -> tuple[
    RateLimitedProvider,
    RequestLimiter,
]:
    """
    Use the same project configuration as Jimmy.

    Settings() loads .env through jimmy.config.settings.
    """

    settings = Settings()

    api_key = settings.gemini_api_key.strip()

    if not api_key:
        raise RuntimeError(
            "Gemini API key is missing from project configuration.",
        )

    model = settings.gemini_model.strip()

    if not model:
        raise RuntimeError(
            "Gemini model is missing from project configuration.",
        )

    provider = GeminiProvider(
        api_key=api_key,
        model=model,
    )

    limiter = RequestLimiter(
        config.requests_per_minute,
        config.request_window_seconds,
    )

    wrapped_provider = RateLimitedProvider(
        provider,
        limiter,
        config.max_rate_limit_retries,
    )

    return (
        wrapped_provider,
        limiter,
    )


# ============================================================
# BUILD JIMMY
# ============================================================


def build_agent(
    workspace: Path,
    config: EvalConfig,
    provider: RateLimitedProvider,
) -> AgentLoop:
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
    if args.task:
        task_id = args.task.upper()

        for task in TASKS:
            if task.id == task_id:
                return [task]

        raise ValueError(
            f"Unknown eval task: {args.task}",
        )

    task_ids = [task.id for task in TASKS]

    start_index = (
        task_ids.index(
            args.start.upper(),
        )
        if args.start
        else 0
    )

    end_index = (
        task_ids.index(
            args.end.upper(),
        )
        if args.end
        else len(TASKS) - 1
    )

    if end_index < start_index:
        raise ValueError(
            "--end must be after --start.",
        )

    return list(TASKS[start_index : end_index + 1])


# ============================================================
# RUN ONE TASK
# ============================================================


def run_task(
    task: EvalTask,
    config: EvalConfig,
    provider: RateLimitedProvider,
    limiter: RequestLimiter,
    keep_workspace: bool,
) -> tuple[
    EvalTrace,
    dict[str, Any],
]:
    workspace = Path(
        tempfile.mkdtemp(
            prefix=(f"jimmy-eval-{task.id.lower()}-"),
        ),
    )

    collector = TraceCollector(
        task.id,
        task.prompt,
        workspace,
    )

    started = time.monotonic()

    wait_count_before = limiter.wait_count

    wait_seconds_before = limiter.wait_seconds

    try:
        # ----------------------------------------------------
        # 1. Prepare clean repository
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

        # IMPORTANT:
        # Capture baseline after the baseline commit.
        baseline = capture_git_state(
            workspace,
        )

        # Add intentionally dirty files for Git tests.
        prepare_post_baseline_changes(
            workspace,
            task,
        )

        # ----------------------------------------------------
        # 2. Build and run Jimmy
        # ----------------------------------------------------

        agent = build_agent(
            workspace=workspace,
            config=config,
            provider=provider,
        )

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
        # 3. Grade actual workspace behavior
        # ----------------------------------------------------

        passed, details = grade_task(
            task=task,
            trace=collector.trace,
            workspace=workspace,
            baseline=baseline,
        )

        collector.trace.passed = passed

        elapsed = time.monotonic() - started

        details["wall_seconds"] = elapsed

        details["rate_limit_waits"] = limiter.wait_count - wait_count_before

        details["rate_limit_wait_seconds"] = limiter.wait_seconds - wait_seconds_before

        details["workspace"] = str(
            workspace,
        )

        return (
            collector.trace,
            details,
        )

    except KeyboardInterrupt:
        raise

    except Exception as exc:
        elapsed = time.monotonic() - started

        collector.fail(
            exc,
        )

        collector.finish(
            "",
        )

        collector.trace.passed = False

        details = {
            "passed": False,
            "reasons": [
                (f"Eval harness error: {type(exc).__name__}: {exc}"),
            ],
            "wall_seconds": elapsed,
            "rate_limit_waits": (limiter.wait_count - wait_count_before),
            "rate_limit_wait_seconds": (limiter.wait_seconds - wait_seconds_before),
            "workspace": str(
                workspace,
            ),
        }

        return (
            collector.trace,
            details,
        )

    finally:
        if not keep_workspace:
            shutil.rmtree(
                workspace,
                ignore_errors=True,
            )


# ============================================================
# PRINT RESULT
# ============================================================


def print_task_result(
    index: int,
    total: int,
    trace: EvalTrace,
    grade: dict[str, Any],
) -> None:
    status = "✅ PASS" if trace.passed else "❌ FAIL"

    print(f"[{index:02d}/{total:02d}] {trace.eval_id} {status}")

    print(f"   {trace.task}")

    print(f"   ⏱ {trace.elapsed_seconds:.1f}s  🧠 turns={trace.turns}  🛠 tools={trace.tool_calls}")

    print(
        f"   ❌ tool failures={trace.failed_tools}"
        f"  🔁 repeats={trace.repeated_tools}"
        f"  🚫 wrong tools={trace.wrong_tool_attempts}"
    )

    changed_files = list(trace.changed_files)

    if changed_files:
        print(
            "   📁 changed: "
            + ", ".join(
                sorted(
                    changed_files,
                ),
            ),
        )

    committed_files = list(
        grade.get(
            "committed_files",
            [],
        ),
    )

    if committed_files:
        print(
            "   📦 committed: "
            + ", ".join(
                sorted(
                    committed_files,
                ),
            ),
        )

    waits = grade.get(
        "rate_limit_waits",
        0,
    )

    wait_seconds = grade.get(
        "rate_limit_wait_seconds",
        0.0,
    )

    if waits:
        print(
            f"   ⏳ rate-limit waits={waits} ({wait_seconds:.1f}s)",
        )

    for reason in grade.get(
        "reasons",
        [],
    ):
        print(
            f"   → {reason}",
        )

    if not trace.passed:
        workspace = grade.get(
            "workspace",
        )

        if workspace:
            print(
                f"   📂 workspace: {workspace}",
            )

    print()


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

    provider, limiter = make_provider(
        config,
    )

    print()
    print("╔══════════════════════════════════════════════╗")
    print("║           JIMMY EVAL HARNESS                ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(f"🧪 Tasks: {len(tasks)}")

    print(f"🚦 Request limit: {config.requests_per_minute} req/min")

    print("📦 Workspace: fresh temporary Git repo")

    print("🔐 Jimmy mode: FULL_ACCESS")

    print("🔁 Execution: sequential")

    print()

    results: list[dict[str, Any]] = []

    for index, task in enumerate(
        tasks,
        start=1,
    ):
        try:
            trace, grade = run_task(
                task=task,
                config=config,
                provider=provider,
                limiter=limiter,
                keep_workspace=(args.keep_workspaces),
            )

        except KeyboardInterrupt:
            print()
            print(
                "⛔ Evaluation interrupted.",
            )
            raise SystemExit(130)

        results.append(
            {
                "trace": trace.to_dict(),
                "grade": grade,
            },
        )

        print_task_result(
            index=index,
            total=len(tasks),
            trace=trace,
            grade=grade,
        )

    # ========================================================
    # SUMMARY
    # ========================================================

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

    report = {
        "summary": {
            "tasks": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / total if total else 0.0),
            "avg_turns": avg_turns,
            "avg_tool_calls": avg_tools,
            "avg_seconds": avg_seconds,
            "tool_failures": (total_tool_failures),
            "wrong_tool_attempts": (total_wrong_tools),
            "repeated_calls": (total_repeats),
            "rate_limit_waits": (limiter.wait_count),
            "rate_limit_wait_seconds": (limiter.wait_seconds),
        },
        "results": results,
    }

    # ========================================================
    # REPORT
    # ========================================================

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

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    print("╔══════════════════════════════════════════════╗")
    print("║               FINAL RESULT                  ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(f"✅ Passed: {passed}/{total}")

    print(f"📊 Pass rate: {report['summary']['pass_rate']:.1%}")

    print(f"🧠 Avg turns: {avg_turns:.2f}")

    print(f"🛠 Avg tools: {avg_tools:.2f}")

    print(f"⏱ Avg task time: {avg_seconds:.1f}s")

    print(f"❌ Tool failures: {total_tool_failures}")

    print(f"🚫 Wrong-tool attempts: {total_wrong_tools}")

    print(f"🔁 Repeated calls: {total_repeats}")

    print(f"⏳ Rate-limit waits: {limiter.wait_count}")

    print(f"⏳ Rate-limit wait time: {limiter.wait_seconds:.1f}s")

    print()

    print(f"📄 Report: {report_path}")

    print()

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
