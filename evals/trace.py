from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
import time


@dataclass
class ToolTrace:
    name: str
    arguments: dict[str, Any]
    elapsed_seconds: float
    success: bool
    message: str = ""


@dataclass
class EvalTrace:
    eval_id: str
    task: str
    workspace: str
    started_at: float
    finished_at: float = 0.0
    result: str = ""
    passed: bool = False
    error: str | None = None
    turns: int = 0
    tool_calls: int = 0
    failed_tools: int = 0
    repeated_tools: int = 0
    wrong_tool_attempts: int = 0
    changed_files: list[str] = field(default_factory=list)
    tool_trace: list[ToolTrace] = field(default_factory=list)

    @property
    def elapsed_seconds(self) -> float:
        return max(0.0, (self.finished_at or time.monotonic()) - self.started_at)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["elapsed_seconds"] = self.elapsed_seconds
        return data


class TraceCollector:
    def __init__(self, eval_id: str, task: str, workspace: Path) -> None:
        self.trace = EvalTrace(
            eval_id=eval_id,
            task=task,
            workspace=str(workspace),
            started_at=time.monotonic(),
        )
        self._last_signature: str | None = None

    def on_event(self, event: Any) -> None:
        kind = getattr(event, "kind", None)

        if kind == "turn_start":
            self.trace.turns = max(
                self.trace.turns,
                int(getattr(event, "turn", 0) or 0),
            )
            return

        if kind == "tool_start":
            name = str(getattr(event, "tool_name", "") or "")
            args = dict(getattr(event, "arguments", {}) or {})
            signature = f"{name}:{args}"

            if signature == self._last_signature:
                self.trace.repeated_tools += 1
            self._last_signature = signature

            self.trace.tool_calls += 1
            self.trace.tool_trace.append(
                ToolTrace(
                    name=name,
                    arguments=args,
                    elapsed_seconds=0.0,
                    success=False,
                )
            )
            return

        if kind == "tool_end" and self.trace.tool_trace:
            current = self.trace.tool_trace[-1]
            current.elapsed_seconds = float(getattr(event, "elapsed", 0.0) or 0.0)
            current.message = str(getattr(event, "message", "") or "")

            if current.message.lower() in {"ok", "success"}:
                current.success = True
            elif current.message.lower() in {"error", "failed", "denied"}:
                self.trace.failed_tools += 1

    def fail(self, exc: Exception) -> None:
        self.trace.error = f"{type(exc).__name__}: {exc}"

    def finish(self, result: str) -> None:
        self.trace.result = result
        self.trace.finished_at = time.monotonic()
