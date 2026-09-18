"""🌿 GitTool — status / diff / add / commit / log in ONE safe tool."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.base import Tool, ToolResult

Action = Literal["status", "diff", "add", "commit", "log"]

# 🚫 never reachable through this tool — force raw shell intent instead
_BLOCKED_SUBCOMMANDS = {"push", "reset", "rebase", "revert", "clean", "filter-branch"}


class GitArgs(BaseModel):
    action: Action = Field(description="Which git operation to run.")
    paths: list[str] = Field(
        default_factory=list,
        description="Files for add (empty = nothing — NEVER use '.' blindly).",
    )
    message: str = Field(
        default="",
        description="Commit message (required for action=commit). Keep it short + one emoji.",
    )
    stat_only: bool = Field(
        default=True,
        description="diff: True = --stat summary (cheap). False = full patch (big!).",
    )
    limit: int = Field(default=20, ge=1, le=100, description="log: number of commits.")


class GitTool(Tool):
    name = "git"
    description = (
        "Run git operations SAFELY: status, diff (stat summary by default), "
        "add specific files, commit with a message, log. Use this instead "
        "of shell for git — it blocks dangerous subcommands (push, reset, "
        "rebase, clean). For 'commit each file separately': call "
        "action=add + action=commit per file, one at a time. Never add "
        "all files with '.' unless the user said to."
    )
    args_schema = GitArgs

    def _run(self, args: list[str]) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                ["git", *args],
                cwd=Path.cwd(),
                capture_output=True,
                text=True,
                timeout=30,
            )
            out = completed.stdout.strip()
            err = completed.stderr.strip()
            return completed.returncode, (out if out else err)
        except FileNotFoundError:
            return 1, "git is not installed"
        except subprocess.TimeoutExpired:
            return 1, "git command timed out"
        except OSError as exc:
            return 1, f"git failed: {exc}"

    def execute(self, arguments: GitArgs) -> ToolResult:
        action = arguments.action

        if action == "status":
            code, out = self._run(["status", "--short", "--branch"])
            return self._wrap(code, out or "(clean working tree)")

        if action == "diff":
            args = ["diff", "--stat"] if arguments.stat_only else ["diff"]
            if arguments.paths:
                args += ["--"] + arguments.paths
            code, out = self._run(args)
            return self._wrap(code, out or "(no changes)")

        if action == "add":
            if not arguments.paths:
                return ToolResult(
                    success=False,
                    output="",
                    error=(
                        "No paths given. List the specific file(s) to stage — "
                        "never stage everything unless the user asked."
                    ),
                )
            code, out = self._run(["add", "--", *arguments.paths])
            return self._wrap(code, f"Staged: {', '.join(arguments.paths)}" if code == 0 else out)

        if action == "commit":
            if not arguments.message.strip():
                return ToolResult(success=False, output="", error="Commit message is required.")
            code, out = self._run(["commit", "-m", arguments.message.strip()])
            return self._wrap(code, out)

        if action == "log":
            code, out = self._run(["log", "--oneline", f"-n{arguments.limit}"])
            return self._wrap(code, out or "(no commits yet)")

        return ToolResult(success=False, output="", error=f"Unknown action: {action}")

    @staticmethod
    def _wrap(code: int, output: str) -> ToolResult:
        return ToolResult(
            success=code == 0,
            output=output,
            error=(f"exit {code}" if code != 0 else None),
        )
