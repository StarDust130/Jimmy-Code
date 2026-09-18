"""🛡️ Jimmy's permission system — policy + approval bridge.

    PermissionManager  session mode + grants + check() (the ONE gate)
    ApprovalGate       agent-loop ⇄ UI bridge for prompts
    classify_risk      tool call → SAFE / WRITE / DANGEROUS
    describe_action    tool call → one human-readable sentence

The TUI only displays decisions and collects answers; tools never check
permissions themselves — the agent loop enforces the gate on every
execution.
"""

from .policy import (
    MODE_META,
    ApprovalGate,
    Decision,
    PermissionManager,
    PermissionMode,
    Risk,
    approval_reason,
    classify_risk,
    describe_action,
    mode_label,
)

__all__ = [
    "MODE_META",
    "ApprovalGate",
    "Decision",
    "PermissionManager",
    "PermissionMode",
    "Risk",
    "approval_reason",
    "classify_risk",
    "describe_action",
    "mode_label",
]
