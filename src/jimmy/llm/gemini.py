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
    """Google Gemini provider for Jimmy."""

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

        pending_tool_responses: list[types.Part] = []

        def flush_tool_responses() -> None:
            if not pending_tool_responses:
                return

            contents.append(
                types.Content(
                    role="user",
                    parts=list(pending_tool_responses),
                )
            )

            pending_tool_responses.clear()

        for message in messages:
            role = message.get("role")
            content = message.get(
                "content",
                "",
            )

            # SYSTEM
            if role == "system":
                if content:
                    system_parts.append(str(content))
                continue

            # USER
            if role == "user":
                flush_tool_responses()

                if content:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[types.Part.from_text(text=str(content))],
                        )
                    )

                continue

            # ASSISTANT / MODEL
            if role == "assistant":
                flush_tool_responses()

                parts: list[types.Part] = []

                if content:
                    parts.append(types.Part.from_text(text=str(content)))

                for call in message.get(
                    "tool_calls",
                    [],
                ):
                    function = call["function"]

                    raw_arguments = function.get(
                        "arguments",
                        {},
                    )

                    if isinstance(
                        raw_arguments,
                        str,
                    ):
                        arguments = json.loads(raw_arguments)
                    else:
                        arguments = raw_arguments

                    if not isinstance(
                        arguments,
                        dict,
                    ):
                        raise TypeError("Assistant tool arguments must be an object.")

                    # IMPORTANT:
                    # Preserve Gemini's thought signature.
                    thought_signature = call.get("thought_signature")

                    function_call = types.FunctionCall(
                        name=function["name"],
                        args=arguments,
                    )

                    part = types.Part(
                        function_call=function_call,
                        thought_signature=(thought_signature),
                    )

                    parts.append(part)

                if parts:
                    contents.append(
                        types.Content(
                            role="model",
                            parts=parts,
                        )
                    )

                continue

            # TOOL RESULT
            if role == "tool":
                pending_tool_responses.append(
                    types.Part.from_function_response(
                        name=message["name"],
                        response={
                            "result": str(content),
                        },
                    )
                )

                continue

        flush_tool_responses()

        system_instruction = "\n\n".join(system_parts) if system_parts else None

        return (
            system_instruction,
            contents,
        )

    @staticmethod
    def _convert_response(
        response: Any,
    ) -> LLMResponse:
        tool_calls: list[ToolCall] = []

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": response.text or "",
        }

        # Read the actual model response parts.
        candidate = response.candidates[0]
        response_parts = candidate.content.parts if candidate.content is not None else []

        serialized_tool_calls: list[dict[str, Any]] = []

        for index, part in enumerate(response_parts):
            function_call = getattr(
                part,
                "function_call",
                None,
            )

            if function_call is None:
                continue

            arguments = dict(function_call.args or {})

            tool_call_id = (
                getattr(
                    function_call,
                    "id",
                    None,
                )
                or f"gemini-call-{index}"
            )

            thought_signature = getattr(
                part,
                "thought_signature",
                None,
            )

            tool_calls.append(
                ToolCall(
                    id=tool_call_id,
                    name=function_call.name,
                    arguments=arguments,
                )
            )

            serialized_call = {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": function_call.name,
                    "arguments": json.dumps(arguments),
                },
            }

            if thought_signature is not None:
                serialized_call["thought_signature"] = thought_signature

            serialized_tool_calls.append(serialized_call)

        if serialized_tool_calls:
            assistant_message["tool_calls"] = serialized_tool_calls

        return LLMResponse(
            content=response.text or "",
            tool_calls=tool_calls,
            assistant_message=assistant_message,
        )

    @staticmethod
    def _normalize_error(
        exc: errors.APIError,
    ) -> LLMProviderError:
        code = getattr(
            exc,
            "code",
            None,
        )

        if code == 400:
            return LLMProviderError(
                message=(f"❌ Gemini rejected the request.\n{exc}"),
                code="invalid_request",
            )

        if code == 401:
            return LLMProviderError(
                message=("❌ Gemini authentication failed.\nCheck your GEMINI_API_KEY."),
                code="authentication_error",
            )

        if code == 403:
            return LLMProviderError(
                message=("❌ Gemini denied the request.\nCheck model access and API permissions."),
                code="permission_error",
            )

        if code == 404:
            return LLMProviderError(
                message=(f"❌ Gemini model was not found.\nModel: {exc}"),
                code="model_not_found",
            )

        if code == 429:
            return LLMProviderError(
                message=("⚠️ Gemini rate limit reached.\nPlease try again later."),
                code="rate_limit",
                retryable=True,
            )

        if code in {
            500,
            502,
            503,
            504,
        }:
            return LLMProviderError(
                message=("⚠️ Gemini is temporarily unavailable.\nPlease try again."),
                code="provider_unavailable",
                retryable=True,
            )

        return LLMProviderError(
            message=(f"❌ Gemini request failed.\n{exc}"),
            code="provider_error",
        )
