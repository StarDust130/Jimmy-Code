from abc import ABC, abstractmethod

from pydantic import BaseModel

from jimmy.tools.models import ToolMetadata, ToolResult


class Tool(ABC):
    """Base contract for every Jimmy tool."""

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
    def metadata(self) -> ToolMetadata:
        raise NotImplementedError

    @property
    @abstractmethod
    def input_model(self) -> type[BaseModel]:
        raise NotImplementedError

    @abstractmethod
    def execute(self, arguments: BaseModel) -> ToolResult:
        raise NotImplementedError
