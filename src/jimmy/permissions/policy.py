"""🛡️ Permission policy — the ONE place that decides allow / ask / deny.

Separate from the TUI and from tools: the agent loop consults this
module before executing any tool; screens only *display* decisions and
collect the user's answer.

Modes:
    🟢 Ask    — everything that changes or executes anything prompts
    🟡 Auto   — safe coding actions (read/search/edit/write/tests) run
                on their own; dangerous ones (shell, git mutations,
                outside-workspace paths) prompt
    🔴 Full   — everything runs without asking

Principles:
    * fail closed — unknown tools / unknown git subcommands prompt
    * never silently escalate — mode changes are user-initiated and the
      app notifies on every change
    * session grants are EXPLICIT user consent ("allow for this session")
"""

from __future__ import annotations

import asyncio
import itertools
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

# ── vocabulary ─────────────────────────────────────────────────────────


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(str, Enum):
    ASK = "ask"
    AUTO = "auto"
    FULL = "full"


class Risk(str, Enum):
    SAFE = "safe"  # read-only
    WRITE = "write"  # mutates workspace files / runs tests
    DANGEROUS = "dangerous"  # executes commands / destructive / escapes workspace


MODE_META: dict[PermissionMode, tuple[str, str, str]] = {
    # mode: (emoji, name, one-line description for the picker)
    PermissionMode.ASK: ("🟢", "Ask", "asks before every action that changes or executes anything"),
    PermissionMode.AUTO: (
        "🟡",
        "Auto",
        "safe coding actions run automatically — dangerous ones ask first",
    ),
    PermissionMode.FULL: (
        "🔴",
        "Full Access",
        "everything runs without asking — for trusted moments",
    ),
}


def mode_label(mode: PermissionMode) -> str:
    """'🟡 Auto' — navbar / palette label."""
    emoji, name, _ = MODE_META[mode]
    return f"{emoji} {name}"


_RISK_REASONS: dict[Risk, str] = {
    Risk.SAFE: "the current permission mode wants a human to confirm this action",
    Risk.WRITE: "this action modifies files in your workspace",
    Risk.DANGEROUS: "this action executes commands or can be destructive",
}


def approval_reason(risk: Risk) -> str:
    return _RISK_REASONS.get(risk, "this action needs your approval")


# ── classification ─────────────────────────────────────────────────────

SAFE_TOOLS = frozenset(
    {"read_files", "read_file", "search_files", "search_file", "grep", "list_files", "glob"}
)
WRITE_TOOLS = frozenset(
    {
        "write_file",
        "write_files",
        "edit_files",
        "edit_file",
        "apply_patch",
        "apply_patch_tool",
        "run_tests",
        "run_tests_tool",
        "test_runner",
    }
)
DANGEROUS_TOOLS = frozenset({"shell", "run_shell", "bash", "exec"})
GIT_TOOLS = frozenset({"git", "git_tool"})

# git subcommands that only READ the repo — everything else fails closed
GIT_READONLY = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "branch",
        "tag",
        "remote",
        "blame",
        "rev-parse",
        "describe",
        "ls-files",
        "reflog",
        "shortlog",
    }
)

_PATH_KEYS: tuple[str, ...] = (
    "path",
    "file_path",
    "filepath",
    "filename",
    "file",
    "paths",
    "files",
    "file_paths",
    "directory",
    "dir",
    "folder",
    "target",
    "test_path",
)


def _escapes_workspace(arguments: dict[str, Any]) -> bool:
    """True if any path argument is absolute or climbs out with '..'."""
    for key in _PATH_KEYS:
        value = arguments.get(key)
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if not isinstance(item, str):
                continue
            text = item.strip()
            if not text:
                continue
            for cls in (PurePosixPath, PureWindowsPath):
                try:
                    path = cls(text)
                except Exception:  # malformed path — let the tool reject it
                    continue
                if ".." in path.parts or path.is_absolute():
                    return True
    return False


def _git_subcommand(arguments: dict[str, Any]) -> str:
    """'git' / 'commit' / args[0] → the subcommand, '' if none."""
    raw = str(
        arguments.get("command") or arguments.get("subcommand") or arguments.get("operation") or ""
    )
    sub = raw.strip().lower()
    if sub.startswith("git"):
        parts = sub.split()
        sub = parts[1] if len(parts) > 1 else ""
    else:
        parts = sub.split()
        sub = parts[0] if parts else ""
    if not sub:
        extra = arguments.get("args")
        if isinstance(extra, (list, tuple)) and extra:
            sub = str(extra[0]).strip().lower()
    return sub


def classify_risk(tool_name: str, arguments: dict[str, Any] | None) -> Risk:
    """Map a tool call to its risk class.  Fails CLOSED on unknowns."""
    args = arguments if isinstance(arguments, dict) else {}
    name = (tool_name or "").strip().lower()

    if name in GIT_TOOLS:
        if _escapes_workspace(args):
            return Risk.DANGEROUS
        return Risk.SAFE if _git_subcommand(args) in GIT_READONLY else Risk.DANGEROUS

    if name in DANGEROUS_TOOLS:
        return Risk.DANGEROUS

    if name in WRITE_TOOLS:
        return Risk.DANGEROUS if _escapes_workspace(args) else Risk.WRITE

    if name in SAFE_TOOLS:
        return Risk.DANGEROUS if _escapes_workspace(args) else Risk.SAFE

    # 🛑 anything we don't recognize needs a human
    return Risk.DANGEROUS


# ── human summary (what WILL happen) ───────────────────────────────────


def _clip(text: str, limit: int = 64) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_action(tool_name: str, arguments: dict[str, Any] | None) -> str:
    """One human sentence: what Jimmy is asking to do."""
    args = arguments if isinstance(arguments, dict) else {}
    name = (tool_name or "").strip().lower()

    def _first(*keys: str) -> str:
        for key in keys:
            value = args.get(key)
            if value:
                return str(value)
        return ""

    if name in DANGEROUS_TOOLS:
        command = _first("command", "cmd")
        return f"run shell command `{_clip(command)}`" if command else "run a shell command"

    if name in GIT_TOOLS:
        bits = ["git"]
        sub = _first("command", "subcommand", "operation")
        if sub:
            bits.append(sub)
        extra = args.get("args")
        if isinstance(extra, (list, tuple)):
            bits.extend(str(x) for x in extra)
        message = _first("message")
        if message:
            bits.extend(["-m", message])
        return f"run `{_clip(' '.join(bits))}`"

    if name in ("write_file", "write_files"):
        target = _first("path", "file_path", "filepath", "filename", "paths", "files")
        return f"write file `{_clip(target)}`" if target else "write a file"

    if name in ("edit_file", "edit_files"):
        target = _first("path", "file_path", "filepath", "filename", "paths", "files")
        return f"edit file `{_clip(target)}`" if target else "edit a file"

    if name in ("apply_patch", "apply_patch_tool"):
        target = _first("path", "file_path", "filepath", "target")
        return f"apply patch to `{_clip(target)}`" if target else "apply a patch"

    if name in ("run_tests", "run_tests_tool", "test_runner"):
        target = _first("test_path", "path", "paths", "pattern", "node_id", "target")
        return f"run tests {_clip(target)}" if target else "run the test suite"

    if name in SAFE_TOOLS:
        target = _first("path", "paths", "query", "pattern", "directory")
        return f"read / search {_clip(target)}" if target else "read the workspace"

    return f"run tool `{name}`"


# ── session state + the ONE gate ───────────────────────────────────────


class PermissionManager:
    """Session permission state — mode, explicit grants, and check().

    Lives on the Agent, so it survives model hot-swaps and applies
    immediately to every subsequent tool call.
    """

    def __init__(self, mode: PermissionMode = PermissionMode.AUTO) -> None:
        self._mode = mode
        self._session_grants: set[str] = set()
        self.gate = ApprovalGate()

    @property
    def mode(self) -> PermissionMode:
        return self._mode

    def set_mode(self, mode: PermissionMode) -> None:
        """Apply immediately — the next check() sees the new mode."""
        self._mode = mode

    def grant_for_session(self, tool_name: str) -> None:
        """🔓 Explicit user consent: this tool never prompts again
        this session (the user pressed 'Allow for this session')."""
        self._session_grants.add((tool_name or "").strip().lower())

    @property
    def session_grants(self) -> frozenset[str]:
        return frozenset(self._session_grants)

    def check(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Decision:
        """🛰️ The ONE decision point — called before EVERY execution."""
        if self._mode is PermissionMode.FULL:
            return Decision.ALLOW

        name = (tool_name or "").strip().lower()
        if name in self._session_grants:
            return Decision.ALLOW

        risk = classify_risk(name, arguments)

        if self._mode is PermissionMode.AUTO:
            return Decision.ALLOW if risk is not Risk.DANGEROUS else Decision.ASK

        # 🟢 Ask — anything that changes or executes anything prompts
        return Decision.ALLOW if risk is Risk.SAFE else Decision.ASK


class ApprovalGate:
    """🌉 Agent loop ⇄ UI bridge for approvals.

    The loop creates a request (the answer-future is registered
    IMMEDIATELY, so a resolver that reacts to the emitted event can
    never race the agent's await), emits it to the UI, and suspends on
    :meth:`wait` until the approval screen resolves it.  If the turn
    dies while waiting (interrupt / clear), :meth:`cancel_all` fails
    everything closed (DENY) — the agent can never hang, and nothing
    ever runs unapproved.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[Decision]] = {}
        self._counter = itertools.count(1)

    def new_request(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        risk: Risk,
        summary: str,
    ) -> dict[str, Any]:
        """Build the request payload the UI displays + pre-register
        its answer-future (race-proof: resolve-before-wait works)."""
        request_id = f"perm-{next(self._counter)}"

        try:
            fut: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
            self._pending[request_id] = fut
        except RuntimeError:
            # No running loop (rare sync caller) — wait() registers it.
            pass

        return {
            "id": request_id,
            "tool": tool_name,
            "arguments": dict(arguments or {}),
            "risk": risk.value,
            "reason": approval_reason(risk),
            "summary": summary,
        }

    async def wait(self, request_id: str) -> Decision:
        """Suspend the agent loop until the UI resolves this request."""
        fut = self._pending.get(request_id)
        if fut is None:
            fut = asyncio.get_running_loop().create_future()
            self._pending[request_id] = fut
        try:
            return await fut
        finally:
            self._pending.pop(request_id, None)

    def resolve(self, request_id: str, decision: Decision) -> bool:
        """UI → agent.  False if the request is gone (turn cancelled)."""
        fut = self._pending.get(request_id)
        if fut is not None and not fut.done():
            fut.set_result(decision)
            return True
        return False

    def pending(self) -> tuple[str, ...]:
        return tuple(self._pending)

    def cancel_all(self) -> None:
        """🛑 Fail closed — every pending request resolves as DENY."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(Decision.DENY)
        self._pending.clear()
