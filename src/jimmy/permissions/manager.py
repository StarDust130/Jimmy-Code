from dataclasses import dataclass
from enum import StrEnum

from jimmy.tools.base import Tool


class PermissionMode(StrEnum):
    ASK = "ask"
    FULL_ACCESS = "full"
    SAFE_ONLY = "safe"


class PermissionAction(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str


class PermissionManager:
    def __init__(
        self,
        mode: PermissionMode = PermissionMode.ASK,
    ) -> None:
        self.mode = mode

    def set_mode(
        self,
        mode: PermissionMode,
    ) -> None:
        self.mode = mode

    def check(
        self,
        tool: Tool,
    ) -> PermissionDecision:
        metadata = tool.metadata

        # ⚡ Full Access
        # Allow every tool without asking.
        if self.mode == PermissionMode.FULL_ACCESS:
            return PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Full access is enabled.",
            )

        # 🔒 Safe Only
        # Read-only tools are allowed automatically.
        # Anything that changes, writes, executes, or commits
        # must ask the user first.
        if self.mode == PermissionMode.SAFE_ONLY:
            if metadata.read_only:
                return PermissionDecision(
                    action=PermissionAction.ALLOW,
                    reason="Tool is read-only.",
                )

            return PermissionDecision(
                action=PermissionAction.ASK,
                reason=(
                    "This action can modify or execute in the workspace and requires your approval."
                ),
            )

        # 🛡 Ask
        # Normal/safe tools run automatically.
        if metadata.read_only:
            return PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Tool is read-only.",
            )

        # Explicit confirmation requirement.
        if metadata.requires_confirmation:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason="This tool requires approval.",
            )

        # Destructive tools require approval.
        if metadata.destructive:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason=("This tool can perform a destructive action."),
            )

        # Normal non-destructive tool.
        return PermissionDecision(
            action=PermissionAction.ALLOW,
            reason="Allowed by policy.",
        )
