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
        # Allow everything without asking.
        if self.mode == PermissionMode.FULL_ACCESS:
            return PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Full access is enabled.",
            )

        # 🔒 Safe Only
        # Safe/read-only tools run automatically.
        # Risky tools require user approval.
        if self.mode == PermissionMode.SAFE_ONLY:
            if metadata.read_only:
                return PermissionDecision(
                    action=PermissionAction.ALLOW,
                    reason="Tool is read-only.",
                )

            return PermissionDecision(
                action=PermissionAction.ASK,
                reason=("This action is not read-only and requires your approval."),
            )

        # 🛡️ Ask
        # Read-only tools run automatically.
        if metadata.read_only:
            return PermissionDecision(
                action=PermissionAction.ALLOW,
                reason="Tool is read-only.",
            )

        if metadata.requires_confirmation:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason="This tool requires approval.",
            )

        if metadata.destructive:
            return PermissionDecision(
                action=PermissionAction.ASK,
                reason=("This tool can perform a destructive action."),
            )

        return PermissionDecision(
            action=PermissionAction.ALLOW,
            reason="Allowed by policy.",
        )
