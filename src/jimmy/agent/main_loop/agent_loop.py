from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jimmy.agent.events import AgentEvent
from jimmy.agent.executor import ToolExecutor
from jimmy.agent.main_loop.agent_main_loop import AgentMainLoop
from jimmy.agent.main_loop.agent_progress import AgentProgress
from jimmy.agent.observer import Observer
from jimmy.agent.planner import Planner
from jimmy.agent.recovery import RecoveryManager
from jimmy.context.context import ContextManager
from jimmy.context.context_summarizer import ContextSummarizer
from jimmy.environment.snapshot import EnvironmentInspector
from jimmy.exploration.explorer import CodebaseExplorer
from jimmy.git.state import GitState
from jimmy.llm.base import LLMProvider
from jimmy.observability.metrics import Observability
from jimmy.permissions.manager import PermissionManager
from jimmy.session.json_store import JsonSessionStore
from jimmy.session.store import SessionStore
from jimmy.state.session import SessionState
from jimmy.tools.registry import ToolRegistry
from jimmy.agent.task_state import TaskState
from jimmy.agent.task_state_builder import build_task_state

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

    A session contains the conversation.

    Each call to run() starts a new task/session.
    continue_session() continues an existing conversation.

    Environment awareness is refreshed at task/session boundaries,
    not before every LLM/tool turn.
    """

    _ENVIRONMENT_MARKER = "<environment_context>"

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
        self.workspace = workspace.resolve()
        self.max_turns = max_turns

        self.planner = (
            planner
            if planner is not None
            else Planner(llm)
        )

        self.executor = (
            executor
            if executor is not None
            else ToolExecutor(tools)
        )

        self.observer = (
            observer
            if observer is not None
            else Observer()
        )

        self.recovery = (
            recovery
            if recovery is not None
            else RecoveryManager()
        )

        self.explorer = (
            explorer
            if explorer is not None
            else CodebaseExplorer(
                self.workspace,
            )
        )

        self.permissions = (
            permission_manager
            if permission_manager is not None
            else PermissionManager()
        )

        # Git is optional because some workspaces are not Git repos.
        self.git_state = git_state

        self.session_store = (
            session_store
            if session_store is not None
            else JsonSessionStore(
                Path.home(),
            )
        )

        self.observability = (
            observability
            if observability is not None
            else Observability()
        )

        self.context_manager = ContextManager(
            summarizer=ContextSummarizer(llm),
        )

        self.environment = EnvironmentInspector(
            self.workspace,
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
            workspace=self.workspace,
        )

        self.current_session_id: str | None = None

    # ============================================================
    # NEW TASK
    # ============================================================

    def run(
        self,
        task: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Start a completely new task.

        A new session is created, so previous conversation messages
        are not reused.

        A fresh environment snapshot is captured once here.
        """

        started_at = time.monotonic()

        task = task.strip()

        if not task:
            raise ValueError(
                "Task cannot be empty.",
            )

        environment_prompt = (
            self.environment
            .snapshot()
            .to_prompt()
        )

        state = SessionState(
            task=task,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "system",
                    "content": environment_prompt,
                },
                {
                    "role": "user",
                    "content": task,
                },
            ],
        )

        session_id = self.session_store.create(
            state,
        )

        self.current_session_id = session_id

        task_state = build_task_state(
            task=task,
            workspace=self.workspace,
        )

        state.add_message(
            self._task_context_message(task_state),
        )

        return self._run_session(
            state=state,
            session_id=session_id,
            started_at=started_at,
            task_state=task_state,
            on_event=on_event,
            on_permission=on_permission,
            on_text_delta=on_text_delta,
        )

    # ============================================================
    # CONTINUE EXISTING SESSION
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
        Continue an existing conversation with a new user request.

        Previous messages remain available for explicit references.

        The new task gets a fresh environment snapshot.
        """

        started_at = time.monotonic()

        task = task.strip()

        if not task:
            raise ValueError(
                "Task cannot be empty.",
            )

        state = self.session_store.load(
            session_id,
        )

        self.current_session_id = session_id

        # A session may contain several completed user requests.  Its saved
        # task is the resumable active request, not the first historical one.
        state.task = task

        # --------------------------------------------------------
        # Explicit task boundary.
        # --------------------------------------------------------

        state.add_message(
            {
                "role": "system",
                "content": (
                    "<task_boundary>\n"
                    "A new user task has started.\n"
                    "The previous task is no longer active.\n"
                    "Use previous conversation only when needed "
                    "to resolve explicit references in the new task.\n"
                    "</task_boundary>"
                ),
            },
        )

        # --------------------------------------------------------
        # Refresh environment because the workspace may have
        # changed since the previous task.
        # --------------------------------------------------------

        self._refresh_environment_context(
            state,
        )

        state.add_message(
            {
                "role": "user",
                "content": task,
            },
        )

        task_state = build_task_state(
            task=task,
            workspace=self.workspace,
        )

        state.add_message(
            self._task_context_message(task_state),
        )

        return self._run_session(
            state=state,
            session_id=session_id,
            started_at=started_at,
            task_state=task_state,
            on_event=on_event,
            on_permission=on_permission,
            on_text_delta=on_text_delta,
        )

    # ============================================================
    # RESUME
    # ============================================================

    def resume(
        self,
        session_id: str,
        on_event: EventHandler | None = None,
        on_permission: PermissionHandler | None = None,
        on_text_delta: TextDeltaHandler | None = None,
    ) -> str:
        """
        Resume an existing saved session/task.

        The workspace may have changed while the process was stopped,
        so refresh the environment snapshot before continuing.
        """

        started_at = time.monotonic()

        state = self.session_store.load(
            session_id,
        )

        self.current_session_id = session_id

        self._refresh_environment_context(
            state,
        )

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        task_state = build_task_state(
            task=state.task,
            workspace=self.workspace,
        )

        return self._run_session(
            state=state,
            session_id=session_id,
            started_at=started_at,
            task_state=task_state,
            on_event=on_event,
            on_permission=on_permission,
            on_text_delta=on_text_delta,
        )

    # ============================================================
    # ENVIRONMENT
    # ============================================================

    @staticmethod
    def _task_context_message(
        task_state: TaskState,
    ) -> dict[str, str]:
        paths = sorted(task_state.requested_paths)
        scope = ", ".join(paths) if paths else "workspace root"
        return {
            "role": "system",
            "content": (
                "<active_task_context>\n"
                f"explicit_target_scope: {scope}\n"
                f"commit_requested: {'yes' if task_state.commit_requested else 'no'}\n"
                f"static_frontend: {'yes' if task_state.static_frontend else 'no'}\n"
                "If the task creates a new standalone folder, implement and "
                "verify that target only. Do not infer that language tools or "
                "test runners from the parent repository apply to it.\n"
                "Do not search, read, verify, or modify sibling folders or the "
                "parent project unless the user explicitly includes them.\n"
                "Do not use git_commit unless commit_requested is yes.\n"
                "</active_task_context>"
            ),
        }

    def _refresh_environment_context(
        self,
        state: SessionState,
    ) -> None:
        """
        Replace stale environment context with a fresh snapshot.

        Only environment-context system messages are replaced.
        The actual conversation remains untouched.
        """

        state.messages = [
            message
            for message in state.messages
            if not self._is_environment_message(
                message,
            )
        ]

        environment_prompt = (
            self.environment
            .snapshot()
            .to_prompt()
        )

        # Place the fresh environment immediately after the
        # initial system prompt whenever possible.
        insert_at = 1 if state.messages else 0

        state.messages.insert(
            insert_at,
            {
                "role": "system",
                "content": environment_prompt,
            },
        )

    @classmethod
    def _is_environment_message(
        cls,
        message: dict[str, Any],
    ) -> bool:
        if message.get("role") != "system":
            return False

        content = str(
            message.get(
                "content",
                "",
            )
            or ""
        )

        return (
            cls._ENVIRONMENT_MARKER
            in content
        )

    # ============================================================
    # RUN SESSION
    # ============================================================

    def _run_session(
        self,
        state: SessionState,
        session_id: str,
        started_at: float,
        task_state: TaskState,
        on_event: EventHandler | None,
        on_permission: PermissionHandler | None,
        on_text_delta: TextDeltaHandler | None,
    ) -> str:
        """
        Execute one task through AgentMainLoop.

        AgentProgress is fresh for this task execution.
        """

        progress = AgentProgress()

        self.session_store.save(
            session_id=session_id,
            state=state,
            status="running",
        )

        metrics = self._start_metrics(
            state=state,
            session_id=session_id,
        )

        try:
            return self.main_loop.run(
                state=state,
                session_id=session_id,
                max_turns=self.max_turns,
                started_at=started_at,
                metrics=metrics,
                progress=progress,
                task_state=task_state,
                on_event=on_event,
                on_permission=on_permission,
                on_text_delta=on_text_delta,
            )

        except KeyboardInterrupt:
            elapsed = time.monotonic() - started_at

            metrics.finish(
                elapsed,
            )

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

            metrics.finish(
                elapsed,
            )

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

    # ============================================================
    # METRICS
    # ============================================================

    def _start_metrics(
        self,
        state: SessionState,
        session_id: str,
    ) -> Any:
        """
        Start run metrics using the current observability API.
        """

        return self.observability.start_run(
            task=state.task,
            session_id=session_id,
        )
