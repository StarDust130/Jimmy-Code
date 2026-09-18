"""🧪 RunTestsTool — verify changes with a SUMMARY, not a firehose."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult

# 🔎 pass/fail counters for common runners
_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERRORS = re.compile(r"(\d+) error")


class RunTestsArgs(BaseModel):
    path: str = Field(
        default="tests",
        description="Test file/directory to run (relative to workspace).",
    )
    runner: str = Field(
        default="auto",
        description="'pytest' | 'npm' | 'auto' (auto-detect from the workspace).",
    )
    timeout: int = Field(default=120, ge=5, le=600)


class RunTestsTool(Tool):
    name = "run_tests"
    description = (
        "Run the project's test suite and return a SHORT summary "
        "(passed/failed counts + failing test names only — never the "
        "full log). Use this ONLY when asked to verify changes or fix a "
        "bug; do not run it after every edit 'just to be safe'."
    )
    args_schema = RunTestsArgs

    # 🧠 runner detection
    def _detect(self, workspace: Path) -> str:
        if (workspace / "pyproject.toml").exists() or (workspace / "pytest.ini").exists():
            return "pytest"
        if (workspace / "package.json").exists():
            return "npm"
        return "pytest"  # sensible default for a python repo

    def _summarize(self, output: str) -> str:
        passed = _PASSED.search(output)
        failed = _FAILED.search(output)
        errors = _ERRORS.search(output)

        bits: list[str] = []
        if passed:
            bits.append(f"{passed.group(1)} passed")
        if failed:
            bits.append(f"{failed.group(1)} FAILED")
        if errors:
            bits.append(f"{errors.group(1)} errors")
        return ", ".join(bits) if bits else "no counts parsed"

    def _failing_names(self, output: str, limit: int = 10) -> list[str]:
        """Extract short failing test ids from pytest-style output."""
        names: list[str] = []
        for line in output.splitlines():
            line = line.strip()
            if line.startswith("FAILED ") or line.startswith("ERROR "):
                name = line.split(None, 1)[1].split(" - ")[0].strip()
                if name and name not in names:
                    names.append(name)
                if len(names) >= limit:
                    break
        return names

    def execute(self, arguments: RunTestsArgs) -> ToolResult:
        workspace = Path.cwd().resolve()
        runner = arguments.runner
        if runner == "auto":
            runner = self._detect(workspace)

        if runner == "pytest":
            cmd = ["python", "-m", "pytest", arguments.path, "-q", "--no-header"]
        elif runner == "npm":
            cmd = (
                ["npx", "vitest", "run", arguments.path]
                if (workspace / "vitest.config.ts").exists()
                else ["npm", "test", "--", arguments.path]
            )
        else:
            return ToolResult(success=False, output="", error=f"Unknown runner: {runner}")

        # 🔒 everything after `--` / positional paths — no shell, no injection
        try:
            completed = subprocess.run(
                cmd,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=arguments.timeout,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                success=False,
                output="",
                error=f"Tests timed out after {arguments.timeout}s.",
            )
        except OSError as exc:
            return ToolResult(success=False, output="", error=f"Failed to start: {exc}")

        output = completed.stdout + "\n" + completed.stderr
        summary = self._summarize(output)
        failures = self._failing_names(output)

        lines = [f"🧪 {runner}: {summary}"]

        if failures:
            lines.append("Failing:")
            lines.extend(f"  - {name}" for name in failures)

        # 🩹 tail of the log — enough to see the first failure, not 500 lines
        tail = "\n".join(output.strip().splitlines()[-15:])
        lines.append("\n--- last output ---")
        lines.append(tail)

        return ToolResult(
            success=completed.returncode == 0,
            output="\n".join(lines),
            error=None if completed.returncode == 0 else f"exit {completed.returncode}",
        )
