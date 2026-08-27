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

EventHandler = Callable[
    [AgentEvent],
    None,
]

PermissionHandler = Callable[
    [str, str, dict[str, Any]],
    bool,
]

TextDeltaHandler = Callable[
    [str],
    None,
]


class AgentLoop:
    """
    Public Jimmy agent interface.

    A session contains the full conversation.

    Each user request inside that session is a separate task.
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

        # Available capabilities.
        # They are available to Jimmy when needed.
        self.planner = planner if planner is not None else Planner(llm)

        self.executor = executor if executor is not None else ToolExecutor(tools)

        self.observer = observer if observer is not None else Observer()

        self.recovery = recovery if recovery is not None else RecoveryManager()

        self.explorer = explorer if explorer is not None else CodebaseExplorer(workspace)

        self.permissions = (
            permission_manager if permission_manager is not None else PermissionManager()
        )

        # Git is optional.
        # Do not construct GitState automatically because
        # some workspaces/tests are not Git repositories.
        self.git_state = git_state

        self.session_store = (
            session_store if session_store is not None else JsonSessionStore(Path.home())
        )

        self.observability = observability if observability is not None else Observability()

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
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Start a brand-new session and task.
        """

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
            on_text_delta=on_text_delta,
        )

    # ============================================================
    # CONTINUE SAME SESSION
    # ============================================================

    def continue_session(
        self,
        session_id: str,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Continue the same conversation with a new user task.

        Previous conversation remains available for context and
        explicit references such as:

            "commit that file"
            "change the same function"

        Previous task instructions are not automatically active.
        """

        task = task.strip()

        if not task:
            raise ValueError("Task cannot be empty.")

        state = self.session_store.load(session_id)

        self.current_session_id = session_id

        # Explicit boundary between tasks inside one session.
        state.add_message(
            {
                "role": "system",
                "content": (
                    "NEW TASK STARTED.\n"
                    "The previous user task is no longer active.\n"
                    "Work only on the new user request below.\n"
                    "Use previous conversation only to resolve "
                    "explicit references such as 'that file', "
                    "'it', 'the same function', or 'those changes'.\n"
                    "Do not continue, repeat, commit, test, revert, "
                    "or modify anything from the previous task unless "
                    "the new request explicitly asks for it."
                ),
            }
        )

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
            on_text_delta=on_text_delta,
        )

    # ============================================================
    # RESUME SESSION
    # ============================================================

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Resume a saved/interrupted session.

        This does not create a new task.
        """

        state = self.session_store.load(session_id)

        self.current_session_id = session_id

        return self._run_session(
            state=state,
            session_id=session_id,
            on_event=on_event,
            on_permission=on_permission,
            on_text_delta=on_text_delta,
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
        on_text_delta: TextDeltaHandler | None,
    ) -> str:
        started_at = time.monotonic()

        self.current_session_id = session_id

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
                on_text_delta=on_text_delta,
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
