"""
🧭 Explorer   → when understanding is needed
📋 Planner    → when task proves complex
✂️ Context    → when context gets large
🔄 Recovery   → when something fails
💾 Session    → always save state
📊 Metrics    → always record
🔐 Permission → before protected action
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop import MainLoop
from jimmy.agent.observer import Observer
from jimmy.agent.planner import Planner
from jimmy.agent.recovery import RecoveryManager
from jimmy.context.context import ContextManager
from jimmy.context.context_summarizer import ContextSummarizer
from jimmy.exploration.explorer import CodebaseExplorer
from jimmy.git.state import GitState
from jimmy.llm.base import LLMProvider
from jimmy.observability.metrics import Observability
from jimmy.permissions.manager import PermissionManager
from jimmy.session.json_store import JsonSessionStore
from jimmy.session.store import SessionStore
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry

from .prompt import SYSTEM_PROMPT

EventHandler = Callable[[AgentEvent], None]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentLoop:
    """
    Public entry point for Jimmy.

    AgentLoop handles:
    - creating/resuming sessions
    - wiring services together
    - starting the main execution loop

    The actual ReAct loop lives in MainLoop.
    """

    def __init__(
        self,
        llm: LLMProvider,
        tools: ToolRegistry,
        workspace: Path,
        max_turns: int = 20,
        planner: Planner | None = None,
        executor: ToolExecutor | None = None,
        observer: Observer | None = None,
        recovery: RecoveryManager | None = None,
        explorer: CodebaseExplorer | None = None,
        git_state: GitState | None = None,
        permission_manager: PermissionManager | None = None,
        session_store: SessionStore | None = None,
        observability: Observability | None = None,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.workspace = workspace
        self.max_turns = max_turns

        # Keep these available for future adaptive use.
        # They are NOT automatically executed for every task.
        self.planner = planner or Planner(llm)
        self.explorer = explorer or CodebaseExplorer(workspace)

        self.executor = executor or ToolExecutor(tools)

        self.observer = observer or Observer()

        self.recovery = recovery or RecoveryManager()

        self.permissions = permission_manager or PermissionManager()

        self.git_state = git_state if git_state is not None else GitState(workspace)

        # Context management is infrastructure.
        # It decides internally whether compression is needed.
        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

        # Persist outside the Git workspace.
        self.session_store = session_store or JsonSessionStore(Path.home())

        self.observability = observability or Observability()

        self.main_loop = MainLoop(
            llm=self.llm,
            tools=self.tools,
            executor=self.executor,
            observer=self.observer,
            recovery=self.recovery,
            context_manager=self.context_manager,
            permissions=self.permissions,
            session_store=self.session_store,
            observability=self.observability,
        )

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        """Start a new Jimmy session."""

        started_at = time.monotonic()

        state = self._create_initial_state(task)

        session_id = self.session_store.create(state)

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        metrics = self.observability.start_run(
            task=task,
            session_id=session_id,
        )

        try:
            return self.main_loop.run(
                state=state,
                session_id=session_id,
                max_turns=self.max_turns,
                started_at=started_at,
                metrics=metrics,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="interrupted",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )

            raise

        except Exception as exc:
            metrics.failures += 1

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": state.turn_count,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="failed",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="failed",
            )

            raise

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        """Resume an existing saved session."""

        state = self.session_store.load(session_id)

        started_at = time.monotonic()

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        metrics = self.observability.start_run(
            task=state.task,
            session_id=session_id,
        )

        try:
            return self.main_loop.run(
                state=state,
                session_id=session_id,
                max_turns=self.max_turns,
                started_at=started_at,
                metrics=metrics,
                on_event=on_event,
                on_permission=on_permission,
            )

        except KeyboardInterrupt:
            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="interrupted",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="interrupted",
            )

            raise

        except Exception as exc:
            metrics.failures += 1

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": state.turn_count,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            metrics.finish(time.monotonic() - started_at)

            self.observability.record_run(
                metrics,
                status="failed",
            )

            self.session_store.save(
                session_id=session_id,
                state=state,
                status="failed",
            )

            raise

    def _create_initial_state(
        self,
        task: str,
    ) -> SessionState:
        """
        Build the smallest initial context.

        Do NOT automatically:
        - run the planner
        - scan the whole repository
        - search files

        The main agent can request those capabilities
        when the task actually needs them.
        """

        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": task,
            },
        ]

        return SessionState(
            task=task,
            messages=messages,
        )
