"""
🧭 Explorer   → when understanding is needed
📋 Planner    → when task proves complex
✂️ Context    → when context gets large
🔄 Recovery   → when something fails
💾 Session    → always save state
📊 Metrics    → always record
🔐 Permission → before protected action
"""

"""
USER
 ↓
AgentMainLoop
 ↓
AgentTurn
 ↓
LLM decides
 ↓
AgentToolRunner
 ↓
tool
 ↓
observation
 ↓
LLM decides again
"""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_main_loop import AgentMainLoop
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

from ..prompt import SYSTEM_PROMPT

EventHandler = Callable[[AgentEvent], None]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]


class AgentLoop:
    """
    Public Jimmy agent interface.

    This class owns session lifecycle and service wiring.

    It does NOT:
    - automatically plan
    - automatically explore
    - automatically inspect Git
    - choose tools
s
    The main agent loop handles those decisions when needed.
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

        self.planner = planner or Planner(llm)

        self.executor = executor or ToolExecutor(tools)

        self.observer = observer or Observer()

        self.recovery = recovery or RecoveryManager()

        self.explorer = explorer or CodebaseExplorer(workspace)

        self.permissions = permission_manager or PermissionManager()

        # IMPORTANT:
        # Do not create GitState automatically.
        #
        # Some workspaces are not Git repositories.
        # GitState is optional and should only exist when
        # the caller explicitly provides it.
        self.git_state = git_state

        self.session_store = session_store or JsonSessionStore(Path.home())

        self.observability = observability or Observability()

        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

        self.main_loop = AgentMainLoop(
            llm=llm,
            tools=tools,
            executor=self.executor,
            observer=self.observer,
            recovery=self.recovery,
            context_manager=self.context_manager,
            permissions=self.permissions,
            session_store=self.session_store,
            observability=self.observability,
        )

        self.current_session_id: str | None = None

    # ============================================================
    # NEW SESSION
    # ============================================================

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        task = task.strip()

        if not task:
            raise ValueError("Task cannot be empty.")

        state = SessionState(
            task=task,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": task,
                },
            ],
        )

        session_id = self.session_store.create(state)

        self.current_session_id = session_id

        return self._run_session(
            state=state,
            session_id=session_id,
            on_event=on_event,
            on_permission=on_permission,
        )

    # ============================================================
    # CONTINUE CURRENT SESSION
    # ============================================================

    def continue_session(
        self,
        session_id: str,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        task = task.strip()

        if not task:
            raise ValueError("Task cannot be empty.")

        state = self.session_store.load(session_id)

        self.current_session_id = session_id

        # IMPORTANT:
        # Keep the entire previous conversation.
        state.add_message(
            {
                "role": "user",
                "content": task,
            }
        )

        return self._run_session(
            state=state,
            session_id=session_id,
            on_event=on_event,
            on_permission=on_permission,
        )

    # ============================================================
    # RESUME SAVED SESSION
    # ============================================================

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
    ) -> str:
        state = self.session_store.load(session_id)

        self.current_session_id = session_id

        return self._run_session(
            state=state,
            session_id=session_id,
            on_event=on_event,
            on_permission=on_permission,
        )

    # ============================================================
    # COMMON EXECUTION
    # ============================================================

    def _run_session(
        self,
        state: SessionState,
        session_id: str,
        on_event: EventHandler | None,
        on_permission: PermissionHandler | None,
    ) -> str:
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
            elapsed = time.monotonic() - started_at

            metrics.finish(elapsed)

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

            elapsed = time.monotonic() - started_at

            self.observability.record(
                "error",
                {
                    "session_id": session_id,
                    "turn": state.turn_count,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )

            metrics.finish(elapsed)

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
