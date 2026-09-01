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

# Allow direct script execution to import the repository packages.
if __package__ in {None, ""}:
    REPO_ROOT = Path(__file__).resolve().parent.parent

    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

from evals.config import EvalConfig
from evals.graders.graders import (
    capture_git_state,
    grade_task,
)
from evals.rate_limit import RateLimitedProvider, RequestLimiter
from evals.tasks.coding_tasks import TASKS, EvalTask
from evals.trace import EvalTrace, TraceCollector
from jimmy.config.settings import Settings
from jimmy.llm.gemini import GeminiProvider

try:
    from jimmy.agent.main_loop.agent_loop import AgentLoop
except ImportError:
    from jimmy.agent.main_loop.agent_loop import AgentLoop

from jimmy.permissions.manager import PermissionManager, PermissionMode
from jimmy.tools.defaults import create_default_registry

# ============================================================
# ARGUMENTS
# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Jimmy coding evals in isolated workspaces.",
    )

    parser.add_argument(
        "--task",
        help="Run one eval, for example E07.",
    )

    parser.add_argument(
        "--start",
        help="First eval id.",
    )

    parser.add_argument(
        "--end",
        help="Last eval id.",
    )

    parser.add_argument(
        "--report",
        default="evals/traces/latest.json",
        help="Output report path.",
    )

    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help="Keep temporary eval workspaces.",
    )

    return parser.parse_args()


# ============================================================
# GIT / PROCESS
# ============================================================


def run_cmd(
    cwd: Path,
    args: list[str],
    *,
    timeout: int = 30,
) -> subprocess.CompletedProcess[str]:
    """
    Run a command and raise on failure.

    Eval setup commands are expected to succeed.
    """

    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def init_git_repo(
    workspace: Path,
) -> None:
    run_cmd(
        workspace,
        [
            "git",
            "init",
        ],
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
    """
    Create exactly the files required by the eval.
    """

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
    Commit the fixture state.

    This commit represents the repository BEFORE Jimmy works.
    """

    run_cmd(
        workspace,
        [
            "git",
            "add",
            ".",
        ],
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
            "✨ eval baseline",
        ],
    )


def prepare_post_baseline_changes(
    workspace: Path,
    task: EvalTask,
) -> None:
    """
    Add intentional changes required by Git evals.

    E09 and E10 need already-dirty files so the agent can commit them.
    """

    if task.id in {"E09", "E10", "E29"}:
        for relative_path in task.files:
            path = workspace / relative_path

            path.write_text(
                path.read_text(
                    encoding="utf-8",
                )
                + "# changed by eval\n",
                encoding="utf-8",
            )


# ============================================================
# LLM
# ============================================================


def make_provider(
    config: EvalConfig,
) -> tuple[Any, RequestLimiter]:
    settings = Settings()

    api_key = settings.gemini_api_key.strip()

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is empty in .env.",
        )

    model = settings.gemini_model.strip()

    if not model:
        raise RuntimeError(
            "GEMINI_MODEL is empty in .env.",
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

    return wrapped_provider, limiter


# ============================================================
# AGENT
# ============================================================


def build_agent(
    workspace: Path,
    config: EvalConfig,
    provider: Any,
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

    ids = [task.id for task in TASKS]

    start = ids.index(args.start.upper()) if args.start else 0

    end = ids.index(args.end.upper()) if args.end else len(TASKS) - 1

    if end < start:
        raise ValueError(
            "--end must be after --start",
        )

    return list(TASKS[start : end + 1])


# ============================================================
# SINGLE TASK
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
    workspace = Path(
        tempfile.mkdtemp(
            prefix=f"jimmy-eval-{task.id.lower()}-",
        ),
    )

    collector = TraceCollector(
        task.id,
        task.prompt,
        workspace,
    )

    started = time.monotonic()

    try:
        # --------------------------------------------------------
        # Prepare isolated repository
        # --------------------------------------------------------

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

        # IMPORTANT:
        #
        # Capture baseline AFTER setup is complete.
        # Jimmy's work begins here.
        baseline = capture_git_state(
            workspace,
        )

        # --------------------------------------------------------
        # Build agent
        # --------------------------------------------------------

        agent = build_agent(
            workspace=workspace,
            config=config,
            provider=provider,
        )

        # --------------------------------------------------------
        # Run Jimmy
        # --------------------------------------------------------

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

        # --------------------------------------------------------
        # Grade
        # --------------------------------------------------------

        passed, details = grade_task(
            task=task,
            trace=collector.trace,
            workspace=workspace,
            baseline=baseline,
        )

        collector.trace.passed = passed

        details["wall_seconds"] = time.monotonic() - started

        details["rate_limit_waits"] = limiter.wait_count

        details["rate_limit_wait_seconds"] = limiter.wait_seconds

        details["workspace"] = str(
            workspace,
        )

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
# OUTPUT
# ============================================================


def print_task_result(
    index: int,
    total: int,
    task: EvalTask,
    trace: EvalTrace,
    grade: dict[str, Any],
) -> None:
    status = "✅ PASS" if trace.passed else "❌ FAIL"

    print(
        f"[{index:02d}/{total:02d}] {task.id} {status}",
    )

    print(
        f"   {task.prompt}",
    )

    print(
        f"   ⏱ {trace.elapsed_seconds:.1f}s  🧠 turns={trace.turns}  🛠 tools={trace.tool_calls}",
    )

    print(
        f"   ❌ tool failures={trace.failed_tools}"
        f"  🔁 repeats={trace.repeated_tools}"
        f"  🚫 wrong tools={trace.wrong_tool_attempts}",
    )

    if trace.changed_files:
        print(
            "   📁 changed: "
            + ", ".join(
                trace.changed_files,
            ),
        )

    committed = grade.get(
        "committed_files",
        [],
    )

    if committed:
        print(
            "   📦 committed: "
            + ", ".join(
                committed,
            ),
        )

    wait_count = grade.get(
        "rate_limit_waits",
        0,
    )

    wait_seconds = grade.get(
        "rate_limit_wait_seconds",
        0.0,
    )

    if wait_count:
        print(
            f"   ⏳ rate-limit waits={wait_count} ({wait_seconds:.1f}s)",
        )

    efficiency = grade.get(
        "efficiency",
    )

    if isinstance(
        efficiency,
        dict,
    ) and efficiency.get(
        "measured",
    ):
        print(
            "   ⚡ efficiency: "
            f"tools={trace.tool_calls}"
            f"/{task.efficiency_max_tools}"
            f"  turns={trace.turns}"
            f"/{task.efficiency_max_turns}",
        )

    for reason in grade.get(
        "reasons",
        [],
    ):
        print(
            f"   → {reason}",
        )

    if grade.get(
        "workspace",
    ):
        print(
            f"   📂 workspace: {grade['workspace']}",
        )

    print()


# ============================================================
# MAIN
# ============================================================


def main() -> None:
    args = parse_args()

    config = EvalConfig(
        keep_workspaces=args.keep_workspaces,
    )

    tasks = select_tasks(
        args,
    )

    try:
        provider, limiter = make_provider(
            config,
        )
    except Exception as exc:
        print(
            "❌ Eval setup failed",
            file=sys.stderr,
        )
        print(
            f"   {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    print("╔══════════════════════════════════════════════╗")
    print("║          JIMMY EVAL HARNESS                 ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    settings = Settings()

    print(
        f"🧪 Tasks: {len(tasks)}",
    )

    print(
        f"🚦 Request limit: {config.requests_per_minute} req/min",
    )

    print(
        "📦 Workspace: fresh temporary Git repo",
    )

    print(
        "🔐 Jimmy mode: FULL_ACCESS",
    )

    print(
        f"🤖 Model: {settings.gemini_model}",
    )

    print(
        "🔁 Execution: sequential",
    )

    print()

    results: list[dict[str, Any]] = []

    run_started = time.monotonic()

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
                keep_workspace=args.keep_workspaces,
            )

        except KeyboardInterrupt:
            print(
                "\n⛔ Evaluation interrupted.",
            )
            raise SystemExit(130)

        except Exception as exc:
            # Keep the harness alive long enough to record the
            # failure rather than destroying the entire run.
            trace = EvalTrace(
                eval_id=task.id,
                task=task.prompt,
                workspace="",
                started_at=time.monotonic(),
                finished_at=time.monotonic(),
                result="",
                passed=False,
                error=(f"{type(exc).__name__}: {exc}"),
                turns=0,
                tool_calls=0,
                failed_tools=0,
                repeated_tools=0,
                wrong_tool_attempts=0,
                changed_files=[],
                tool_trace=[],
            )

            grade = {
                "passed": False,
                "reasons": [
                    (f"Eval harness error: {type(exc).__name__}: {exc}"),
                ],
                "used_tools": [],
                "changed_files": [],
                "committed_files": [],
                "uncommitted_files": [],
                "workspace": "",
            }

        results.append(
            {
                "trace": trace.to_dict(),
                "grade": grade,
            },
        )

        print_task_result(
            index=index,
            total=len(tasks),
            task=task,
            trace=trace,
            grade=grade,
        )

    # ========================================================
    # SUMMARY
    # ========================================================

    total = len(
        results,
    )

    passed = sum(1 for item in results if item["trace"]["passed"])

    failed = total - passed

    avg_turns = sum(item["trace"]["turns"] for item in results) / total if total else 0.0

    avg_tools = sum(item["trace"]["tool_calls"] for item in results) / total if total else 0.0

    avg_seconds = (
        sum(item["trace"]["elapsed_seconds"] for item in results) / total if total else 0.0
    )

    tool_failures = sum(item["trace"]["failed_tools"] for item in results)

    wrong_tools = sum(item["trace"]["wrong_tool_attempts"] for item in results)

    repeated_calls = sum(item["trace"]["repeated_tools"] for item in results)

    report = {
        "summary": {
            "tasks": total,
            "passed": passed,
            "failed": failed,
            "pass_rate": (passed / total if total else 0.0),
            "avg_turns": avg_turns,
            "avg_tool_calls": avg_tools,
            "avg_seconds": avg_seconds,
            "tool_failures": tool_failures,
            "wrong_tool_attempts": wrong_tools,
            "repeated_calls": repeated_calls,
            "rate_limit_waits": limiter.wait_count,
            "rate_limit_wait_seconds": limiter.wait_seconds,
            "total_wall_seconds": (time.monotonic() - run_started),
        },
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

    print("╔══════════════════════════════════════════════╗")
    print("║              FINAL RESULT                   ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(
        f"✅ Passed: {passed}/{total}",
    )

    print(
        f"📊 Pass rate: {report['summary']['pass_rate']:.1%}",
    )

    print(
        f"🧠 Avg turns: {avg_turns:.2f}",
    )

    print(
        f"🛠 Avg tools: {avg_tools:.2f}",
    )

    print(
        f"⏱ Avg task time: {avg_seconds:.1f}s",
    )

    print(
        f"❌ Tool failures: {tool_failures}",
    )

    print(
        f"🚫 Wrong-tool attempts: {wrong_tools}",
    )

    print(
        f"🔁 Repeated calls: {repeated_calls}",
    )

    print(
        f"⏳ Rate-limit waits: {limiter.wait_count}",
    )

    print(
        f"⏳ Rate-limit wait time: {limiter.wait_seconds:.1f}s",
    )

    print()

    print(
        f"📄 Report: {report_path}",
    )

    print()

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
