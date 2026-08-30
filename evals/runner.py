from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

# ------------------------------------------------------------
# Package-mode / direct-script compatibility
# ------------------------------------------------------------

if __package__ in {None, ""}:
    import sys

    repo_root = Path(__file__).resolve().parent.parent

    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


# ------------------------------------------------------------
# Eval imports
# ------------------------------------------------------------

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

from jimmy.config import Settings
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
        description=("Run Jimmy coding evaluations in isolated temporary workspaces.")
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
        help="Path to the JSON report.",
    )

    parser.add_argument(
        "--keep-workspaces",
        action="store_true",
        help=("Keep temporary eval workspaces for inspection."),
    )

    return parser.parse_args()


# ============================================================
# COMMAND HELPERS
# ============================================================


def run_cmd(
    cwd: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
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
# GIT FIXTURE SETUP
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
    Create a baseline commit when fixture files exist.

    Empty repositories are also valid.
    """

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
    Make intentional dirty files after the baseline.

    Used by Git scope evaluations.
    """

    if task.id not in {
        "E09",
        "E10",
    }:
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
# LLM PROVIDER
# ============================================================


def make_provider(
    config: EvalConfig,
) -> tuple[
    RateLimitedProvider,
    RequestLimiter,
]:
    """
    Use the same Settings/.env configuration as Jimmy.

    No manual export of GEMINI_API_KEY is required.
    """

    settings = Settings()

    api_key = settings.gemini_api_key.strip()

    if not api_key:
        raise RuntimeError("Gemini API key is empty in the project .env.")

    model = settings.gemini_model

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
# BUILD REAL JIMMY
# ============================================================


def build_agent(
    workspace: Path,
    config: EvalConfig,
    provider: Any,
) -> AgentLoop:
    """
    Build the actual Jimmy agent.

    The workspace is the temporary eval repository,
    NOT the Jimmy source repository.
    """

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

        raise ValueError(f"Unknown eval task: {args.task}")

    ids = [task.id for task in TASKS]

    start_index = 0

    if args.start:
        start_id = args.start.upper()

        if start_id not in ids:
            raise ValueError(f"Unknown --start eval: {args.start}")

        start_index = ids.index(start_id)

    end_index = len(TASKS) - 1

    if args.end:
        end_id = args.end.upper()

        if end_id not in ids:
            raise ValueError(f"Unknown --end eval: {args.end}")

        end_index = ids.index(end_id)

    if end_index < start_index:
        raise ValueError("--end must be after --start.")

    return list(TASKS[start_index : end_index + 1])


# ============================================================
# RUN ONE TASK
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

    workspace = Path(tempfile.mkdtemp(prefix=(f"jimmy-eval-{task.id.lower()}-")))

    collector = TraceCollector(
        eval_id=task.id,
        task=task.prompt,
        workspace=workspace,
    )

    try:
        # ----------------------------------------------------
        # 1. Prepare isolated Git repository
        # ----------------------------------------------------

        init_git_repo(workspace)

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
        # 2. Capture exact state Jimmy receives
        # ----------------------------------------------------

        baseline: GitStateSnapshot = capture_git_state(workspace)

        # ----------------------------------------------------
        # 3. Build real Jimmy
        # ----------------------------------------------------

        agent = build_agent(
            workspace=workspace,
            config=config,
            provider=provider,
        )

        # Save rate-limit counters before this task.
        waits_before = limiter.wait_count
        wait_seconds_before = limiter.wait_seconds

        started = time.monotonic()

        # ----------------------------------------------------
        # 4. Run Jimmy
        # ----------------------------------------------------

        try:
            result = agent.run(
                task.prompt,
                on_event=collector.on_event,
            )

        except KeyboardInterrupt:
            raise

        except Exception as exc:
            collector.fail(exc)
            result = ""

        collector.finish(result)

        # ----------------------------------------------------
        # 5. Grade final workspace state
        # ----------------------------------------------------

        passed, details = grade_task(
            task=task,
            trace=collector.trace,
            workspace=workspace,
            baseline=baseline,
        )

        collector.trace.passed = passed

        # ----------------------------------------------------
        # 6. Per-task metrics
        # ----------------------------------------------------

        details["wall_seconds"] = time.monotonic() - started

        details["rate_limit_waits"] = limiter.wait_count - waits_before

        details["rate_limit_wait_seconds"] = limiter.wait_seconds - wait_seconds_before

        if keep_workspace:
            details["workspace"] = str(workspace)

        return (
            collector.trace,
            details,
        )

    except Exception as exc:
        # Harness failure must be clearly separated from
        # Jimmy task failure.
        collector.fail(exc)

        collector.finish("")

        collector.trace.passed = False

        return (
            collector.trace,
            {
                "passed": False,
                "harness_error": (f"{type(exc).__name__}: {exc}"),
                "reasons": ["Eval harness failed before a reliable task grade was produced."],
            },
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

    waits = int(
        grade.get(
            "rate_limit_waits",
            0,
        )
        or 0
    )

    wait_seconds = float(
        grade.get(
            "rate_limit_wait_seconds",
            0.0,
        )
        or 0.0
    )

    if waits:
        print(f"    ⏳ rate-limit waits={waits} ({wait_seconds:.1f}s)")

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

    for reason in grade.get(
        "reasons",
        [],
    ):
        print(f"    → {reason}")

    if grade.get("harness_error"):
        print("    ⚠️ HARNESS ERROR: " + str(grade["harness_error"]))

    if grade.get("workspace"):
        print("    📂 workspace: " + str(grade["workspace"]))

    print()


# ============================================================
# SUMMARY
# ============================================================


def build_summary(
    results: list[dict[str, Any]],
) -> dict[str, Any]:

    total = len(results)

    passed = sum(1 for item in results if item["trace"]["passed"])

    total_tool_failures = sum(item["trace"]["failed_tools"] for item in results)

    total_wrong_tools = sum(item["trace"]["wrong_tool_attempts"] for item in results)

    total_repeats = sum(item["trace"]["repeated_tools"] for item in results)

    avg_turns = sum(item["trace"]["turns"] for item in results) / total if total else 0.0

    avg_tools = sum(item["trace"]["tool_calls"] for item in results) / total if total else 0.0

    avg_seconds = (
        sum(item["trace"]["elapsed_seconds"] for item in results) / total if total else 0.0
    )

    total_waits = sum(
        int(
            item["grade"].get(
                "rate_limit_waits",
                0,
            )
            or 0
        )
        for item in results
    )

    total_wait_seconds = sum(
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
        "failed": total - passed,
        "pass_rate": (passed / total if total else 0.0),
        "avg_turns": avg_turns,
        "avg_tool_calls": avg_tools,
        "avg_seconds": avg_seconds,
        "tool_failures": total_tool_failures,
        "wrong_tool_attempts": total_wrong_tools,
        "repeated_calls": total_repeats,
        "rate_limit_waits": total_waits,
        "rate_limit_wait_seconds": (total_wait_seconds),
    }


# ============================================================
# MAIN
# ============================================================


def main() -> None:

    args = parse_args()

    config = EvalConfig(keep_workspaces=(args.keep_workspaces))

    tasks = select_tasks(args)

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

    # Settings() loads .env through Jimmy's existing
    # pydantic-settings configuration.
    provider, limiter = make_provider(config)

    results: list[dict[str, Any]] = []

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
    # Final summary
    # --------------------------------------------------------

    summary = build_summary(results)

    report = {
        "summary": summary,
        "results": results,
    }

    report_path = Path(args.report)

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
    print("║                 FINAL RESULT                ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    print(f"✅ Passed: {summary['passed']}/{summary['tasks']}")

    print(f"📊 Pass rate: {summary['pass_rate']:.1%}")

    print(f"🧠 Avg turns: {summary['avg_turns']:.2f}")

    print(f"🛠 Avg tools: {summary['avg_tool_calls']:.2f}")

    print(f"⏱ Avg task time: {summary['avg_seconds']:.1f}s")

    print(f"❌ Tool failures: {summary['tool_failures']}")

    print(f"🚫 Wrong-tool attempts: {summary['wrong_tool_attempts']}")

    print(f"🔁 Repeated calls: {summary['repeated_calls']}")

    print(f"⏳ Rate-limit waits: {summary['rate_limit_waits']}")

    print(f"⏳ Rate-limit wait time: {summary['rate_limit_wait_seconds']:.1f}s")

    print()

    print(f"📄 Report: {report_path}")

    print()

    if summary["failed"] > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
