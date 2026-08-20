from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base interface for every Jimmy tool."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool name."""
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """Tell the LLM what this tool does."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> Any:
        """Execute the tool with validated arguments."""
        raise NotImplementedError
