from groq import Groq

from jimmy.llm.base import LLMProvider
from jimmy.llm.models import LLMResponse


class GroqProvider(LLMProvider):
    def __init__(self, api_key: str, model: str):
        self.client = Groq(api_key=api_key)
        self.model = model

    def chat(self, message: str) -> LLMResponse:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "user",
                    "content": message,
                }
            ],
        )

        return LLMResponse(content=response.choices[0].message.content or "")
