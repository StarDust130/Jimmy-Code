import json
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float | None = None

    @classmethod
    def from_dict(
        cls,
        usage: dict[str, Any] | None,
    ) -> "LLMUsage":
        if not usage:
            return cls()

        input_tokens = int(
            usage.get(
                "input_tokens",
                usage.get(
                    "prompt_tokens",
                    0,
                ),
            )
            or 0
        )

        output_tokens = int(
            usage.get(
                "output_tokens",
                usage.get(
                    "completion_tokens",
                    0,
                ),
            )
            or 0
        )

        total_tokens = int(
            usage.get(
                "total_tokens",
                input_tokens + output_tokens,
            )
            or 0
        )

        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=int(
                usage.get(
                    "cached_tokens",
                    0,
                )
                or 0
            ),
            reasoning_tokens=int(
                usage.get(
                    "reasoning_tokens",
                    usage.get(
                        "thoughts_tokens",
                        0,
                    ),
                )
                or 0
            ),
            cost_usd=(float(usage["cost_usd"]) if usage.get("cost_usd") is not None else None),
        )


@dataclass
class RunMetrics:
    session_id: str | None = None
    task: str = ""

    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    ended_at: str | None = None

    turns: int = 0
    llm_calls: int = 0
    tool_calls: int = 0

    total_elapsed: float = 0.0

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    cost_usd: float = 0.0
    cost_known: bool = True

    failures: int = 0

    tool_elapsed: dict[str, float] = field(default_factory=dict)

    model_calls: dict[str, int] = field(default_factory=dict)

    def finish(
        self,
        elapsed: float,
    ) -> None:
        self.total_elapsed = elapsed
        self.ended_at = datetime.now(UTC).isoformat()

    def add_llm_usage(
        self,
        model: str,
        usage: LLMUsage,
    ) -> None:
        self.llm_calls += 1

        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.total_tokens += usage.total_tokens

        self.model_calls[model] = self.model_calls.get(model, 0) + 1

        if usage.cost_usd is None:
            self.cost_known = False
        else:
            self.cost_usd += usage.cost_usd

    def add_tool_time(
        self,
        tool_name: str,
        elapsed: float,
    ) -> None:
        self.tool_calls += 1

        self.tool_elapsed[tool_name] = (
            self.tool_elapsed.get(
                tool_name,
                0.0,
            )
            + elapsed
        )


class Observability:
    """
    Small runtime metrics collector.

    Metrics are kept in memory for the current run and
    appended to JSONL for later analysis.
    """

    def __init__(
        self,
        root: Path | None = None,
    ) -> None:
        storage_root = root if root is not None else Path.home() / ".jimmy"

        self.directory = storage_root / "observability"

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.events_path = self.directory / "events.jsonl"

        self._lock = threading.Lock()

    def start_run(
        self,
        task: str,
        session_id: str | None = None,
    ) -> RunMetrics:
        return RunMetrics(
            task=task,
            session_id=session_id,
        )

    def record(
        self,
        event: str,
        data: dict[str, Any],
    ) -> None:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **data,
        }

        line = json.dumps(
            payload,
            ensure_ascii=False,
        )

        with (
            self._lock,
            self.events_path.open(
                "a",
                encoding="utf-8",
            ) as file,
        ):
            file.write(line + "\n")

    def record_run(
        self,
        metrics: RunMetrics,
        status: str,
    ) -> None:
        self.record(
            "run_completed",
            {
                "session_id": metrics.session_id,
                "task": metrics.task,
                "status": status,
                "turns": metrics.turns,
                "llm_calls": metrics.llm_calls,
                "tool_calls": metrics.tool_calls,
                "elapsed_seconds": (metrics.total_elapsed),
                "input_tokens": (metrics.input_tokens),
                "output_tokens": (metrics.output_tokens),
                "total_tokens": (metrics.total_tokens),
                "cost_usd": (metrics.cost_usd if metrics.cost_known else None),
                "cost_known": (metrics.cost_known),
                "failures": metrics.failures,
                "tool_elapsed": (metrics.tool_elapsed),
                "model_calls": (metrics.model_calls),
            },
        )
