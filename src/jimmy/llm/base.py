from abc import ABC, abstractmethod

from jimmy.llm.models import LLMResponse


class LLMProvider(ABC):
    """Interface every LLM provider must implement."""

    @abstractmethod
    def chat(self, message: str) -> LLMResponse:
        """Send a message to the model."""
        raise NotImplementedError
