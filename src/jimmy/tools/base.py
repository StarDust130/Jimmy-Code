from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base interface for every Jimmy tool."""

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """JSON schema describing the tool arguments."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError
