import json
from typing import Any

from google import genai
from google.genai import errors, types

from jimmy.llm.base import (
    LLMProvider,
    LLMResponse,
    ToolCall,
)
from jimmy.llm.errors import LLMProviderError


class GeminiProvider(LLMProvider):
    """Google Gemini implementation for Jimmy."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
    ) -> None:
        self.model = model

        self.client = genai.Client(
            api_key=api_key,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        system_instruction, contents = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._convert_tools(tools) or None,
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )

        except errors.APIError as exc:
            raise self._normalize_error(exc) from exc

        except Exception as exc:
            raise LLMProviderError(
                message=(f"❌ Gemini request failed.\n{exc}"),
                code="provider_error",
            ) from exc

        return self._convert_response(response)

    @staticmethod
    def _convert_tools(
        tools: list[dict[str, Any]] | None,
    ) -> list[types.Tool]:
        if not tools:
            return []

        declarations: list[types.FunctionDeclaration] = []

        for tool in tools:
            function = tool["function"]

            declarations.append(
                types.FunctionDeclaration(
                    name=function["name"],
                    description=function.get(
                        "description",
                        "",
                    ),
                    parameters_json_schema=function.get(
                        "parameters",
                        {
                            "type": "object",
                        },
                    ),
                )
            )

        return [
            types.Tool(
                function_declarations=declarations,
            )
        ]

    @staticmethod
    def _convert_messages(
        messages: list[dict[str, Any]],
    ) -> tuple[
        str | None,
        list[types.Content],
    ]:
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for message in messages:
            role = message.get("role")
            content = message.get(
                "content",
                "",
            )

            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue

            if role == "user":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=str(content))],
                    )
                )
                continue

            if role == "assistant":
                parts: list[types.Part] = []

                if content:
                    parts.append(types.Part.from_text(text=str(content)))

                for call in message.get(
                    "tool_calls",
                    [],
                ):
                    function = call["function"]

                    parts.append(
                        types.Part.from_function_call(
                            name=function["name"],
                            args=json.loads(function["arguments"]),
                        )
                    )

                if parts:
                    contents.append(
                        types.Content(
                            role="model",
                            parts=parts,
                        )
                    )

                continue

            if role == "tool":
                contents.append(
                    types.Content(
                        role="tool",
                        parts=[
                            types.Part.from_function_response(
                                name=message["name"],
                                response={
                                    "result": content,
                                },
                            )
                        ],
                    )
                )

        system_instruction = "\n\n".join(system_parts) if system_parts else None

        return system_instruction, contents

    @staticmethod
    def _convert_response(
        response: Any,
    ) -> LLMResponse:
        tool_calls: list[ToolCall] = []

        if response.function_calls:
            for index, function_call in enumerate(response.function_calls):
                tool_calls.append(
                    ToolCall(
                        id=f"gemini-call-{index}",
                        name=function_call.name,
                        arguments=dict(function_call.args or {}),
                    )
                )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": response.text or "",
        }

        if tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in tool_calls
            ]

        return LLMResponse(
            content=response.text or "",
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )

    @staticmethod
    def _normalize_error(
        exc: errors.APIError,
    ) -> LLMProviderError:
        code = getattr(exc, "code", None)

        if code == 401:
            return LLMProviderError(
                message=("❌ Gemini authentication failed.\nCheck your GEMINI_API_KEY."),
                code="authentication_error",
            )

        if code == 429:
            return LLMProviderError(
                message=("⚠️ Gemini rate limit reached.\nPlease try again later."),
                code="rate_limit",
                retryable=True,
            )

        if code in {500, 502, 503, 504}:
            return LLMProviderError(
                message=("⚠️ Gemini is temporarily unavailable."),
                code="provider_unavailable",
                retryable=True,
            )

        return LLMProviderError(
            message=(f"❌ Gemini request failed.\n{exc}"),
            code="provider_error",
        )
