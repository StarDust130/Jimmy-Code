class PermissionRequired(Exception):
    """Jimmy must pause until the user decides."""

    def __init__(
        self,
        tool_name: str,
        reason: str,
        arguments: dict,
    ) -> None:
        self.tool_name = tool_name
        self.reason = reason
        self.arguments = arguments

        super().__init__(f"Permission required for '{tool_name}': {reason}")
