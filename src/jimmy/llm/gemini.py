from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterator
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
    """
    Gemini provider for Jimmy.

    Keep Gemini-specific protocol handling here.
    Jimmy's agent loop remains provider-agnostic.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        timeout_ms: int = 180_000,
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "Gemini API key must not be empty.",
            )

        if not model.strip():
            raise ValueError(
                "Gemini model must not be empty.",
            )

        self.model = model

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
            ),
        )

    # ============================================================
    # CHAT
    # ============================================================

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        system_instruction, contents = (
            self._convert_messages(messages)
        )

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
                message=(
                    "❌ Gemini request failed.\n"
                    f"{exc}"
                ),
                code="provider_error",
            ) from exc

        return self._convert_response(response)

    # ============================================================
    # STREAM
    # ============================================================

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str | LLMResponse]:
        system_instruction, contents = (
            self._convert_messages(messages)
        )

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._convert_tools(tools) or None,
        )

        text_parts: list[str] = []

        # One record per function-call part.
        records: dict[
            tuple[int, str],
            dict[str, Any],
        ] = {}

        usage: dict[str, Any] | None = None

        try:
            response_stream = (
                self.client.models.generate_content_stream(
                    model=self.model,
                    contents=contents,
                    config=config,
                )
            )

            for chunk in response_stream:
                text = getattr(
                    chunk,
                    "text",
                    None,
                )

                if isinstance(text, str) and text:
                    text_parts.append(text)
                    yield text

                usage_metadata = getattr(
                    chunk,
                    "usage_metadata",
                    None,
                )

                if usage_metadata is not None:
                    usage = self._usage_from_metadata(
                        usage_metadata,
                    )

                candidates = (
                    getattr(
                        chunk,
                        "candidates",
                        None,
                    )
                    or []
                )

                if not candidates:
                    continue

                candidate = candidates[0]

                candidate_content = getattr(
                    candidate,
                    "content",
                    None,
                )

                if candidate_content is None:
                    continue

                parts = (
                    getattr(
                        candidate_content,
                        "parts",
                        None,
                    )
                    or []
                )

                for part_index, part in enumerate(parts):
                    function_call = getattr(
                        part,
                        "function_call",
                        None,
                    )

                    if function_call is None:
                        continue

                    name = getattr(
                        function_call,
                        "name",
                        None,
                    )

                    if not isinstance(name, str) or not name:
                        continue

                    key = (
                        part_index,
                        name,
                    )

                    record = records.setdefault(
                        key,
                        {
                            "name": name,
                            "id": None,
                            "arguments": {},
                            "thought_signature": None,
                        },
                    )

                    call_id = getattr(
                        function_call,
                        "id",
                        None,
                    )

                    if isinstance(call_id, str) and call_id:
                        record["id"] = call_id

                    args = getattr(
                        function_call,
                        "args",
                        None,
                    )

                    if isinstance(args, dict):
                        record["arguments"].update(args)

                    signature = getattr(
                        part,
                        "thought_signature",
                        None,
                    )

                    if signature is not None:
                        record["thought_signature"] = (
                            self._signature_for_storage(
                                signature,
                            )
                        )

        except errors.APIError as exc:
            raise self._normalize_error(exc) from exc
        except Exception as exc:
            raise LLMProviderError(
                message=(
                    "❌ Gemini streaming request failed.\n"
                    f"{exc}"
                ),
                code="provider_error",
            ) from exc

        content = "".join(text_parts)

        tool_calls: list[ToolCall] = []
        serialized_tool_calls: list[dict[str, Any]] = []

        for index, record in enumerate(records.values()):
            call_id = (
                record["id"]
                or f"gemini-call-{index}"
            )

            arguments = dict(
                record["arguments"] or {},
            )

            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=record["name"],
                    arguments=arguments,
                ),
            )

            serialized_call: dict[str, Any] = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": record["name"],
                    "arguments": json.dumps(
                        arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }

            signature = record.get(
                "thought_signature",
            )

            if signature:
                serialized_call[
                    "thought_signature"
                ] = signature

            serialized_tool_calls.append(
                serialized_call,
            )

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }

        if serialized_tool_calls:
            assistant_message[
                "tool_calls"
            ] = serialized_tool_calls

        yield LLMResponse(
            content=content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=usage,
        )

    # ============================================================
    # TOOLS
    # ============================================================

    @staticmethod
    def _convert_tools(
        tools: list[dict[str, Any]] | None,
    ) -> list[types.Tool]:
        if not tools:
            return []

        declarations: list[dict[str, Any]] = []

        for tool in tools:
            function = tool.get(
                "function",
                {},
            )

            if not isinstance(function, dict):
                continue

            name = function.get("name")

            if not isinstance(name, str) or not name:
                continue

            declarations.append(
                {
                    "name": name,
                    "description": function.get(
                        "description",
                        "",
                    ),
                    "parameters_json_schema": function.get(
                        "parameters",
                        {
                            "type": "object",
                        },
                    ),
                },
            )

        if not declarations:
            return []

        return [
            types.Tool(
                function_declarations=declarations,
            )
        ]

    # ============================================================
    # HISTORY
    # ============================================================

    @classmethod
    def _convert_messages(
        cls,
        messages: list[dict[str, Any]],
    ) -> tuple[
        str | None,
        list[types.Content],
    ]:
        """
        Convert Jimmy's history into Gemini Generate Content history.

        Gemini function-calling sequence:

            user
            model(function_call)
            user(function_response)
            model(...)
        """

        system_parts: list[str] = []
        contents: list[types.Content] = []

        index = 0

        while index < len(messages):
            message = messages[index]

            role = message.get("role")

            # ====================================================
            # SYSTEM
            # ====================================================

            if role == "system":
                content = str(
                    message.get(
                        "content",
                        "",
                    )
                    or ""
                )

                if content:
                    system_parts.append(content)

                index += 1
                continue

            # ====================================================
            # USER
            # ====================================================

            if role == "user":
                content = str(
                    message.get(
                        "content",
                        "",
                    )
                    or ""
                )

                if content:
                    contents.append(
                        types.Content(
                            role="user",
                            parts=[
                                types.Part.from_text(
                                    text=content,
                                )
                            ],
                        )
                    )

                index += 1
                continue

            # ====================================================
            # ASSISTANT
            # ====================================================

            if role == "assistant":
                raw_calls = message.get(
                    "tool_calls",
                    [],
                )

                if not isinstance(raw_calls, list):
                    raw_calls = []

                model_parts: list[types.Part] = []

                text = str(
                    message.get(
                        "content",
                        "",
                    )
                    or ""
                )

                if text:
                    model_parts.append(
                        types.Part.from_text(
                            text=text,
                        )
                    )

                calls: list[
                    dict[str, str]
                ] = []

                for raw_call in raw_calls:
                    if not isinstance(raw_call, dict):
                        raise ValueError(
                            "Invalid Gemini history: "
                            "tool call must be an object.",
                        )

                    function = raw_call.get(
                        "function",
                        {},
                    )

                    if not isinstance(function, dict):
                        raise ValueError(
                            "Invalid Gemini history: "
                            "tool call function must be an object.",
                        )

                    name = function.get("name")

                    if not isinstance(name, str) or not name:
                        raise ValueError(
                            "Invalid Gemini history: "
                            "tool call is missing its name.",
                        )

                    arguments = cls._parse_arguments(
                        function.get(
                            "arguments",
                            {},
                        ),
                    )

                    call_id = str(
                        raw_call.get(
                            "id",
                            "",
                        )
                        or ""
                    )

                    signature = cls._decode_signature(
                        raw_call.get(
                            "thought_signature",
                        ),
                    )

                    function_call = types.FunctionCall(
                        id=call_id or None,
                        name=name,
                        args=arguments,
                    )

                    part = types.Part(
                        function_call=function_call,
                        thought_signature=signature,
                    )

                    model_parts.append(part)

                    calls.append(
                        {
                            "id": call_id,
                            "name": name,
                        },
                    )

                # ------------------------------------------------
                # Normal assistant message.
                # ------------------------------------------------

                if not calls:
                    if model_parts:
                        contents.append(
                            types.Content(
                                role="model",
                                parts=model_parts,
                            )
                        )

                    index += 1
                    continue

                # ------------------------------------------------
                # Model tool call.
                # ------------------------------------------------

                contents.append(
                    types.Content(
                        role="model",
                        parts=model_parts,
                    )
                )

                # ------------------------------------------------
                # Tool responses must immediately follow.
                # ------------------------------------------------

                next_index = index + 1

                tool_messages: list[
                    dict[str, Any]
                ] = []

                while (
                    next_index < len(messages)
                    and messages[next_index].get(
                        "role",
                    )
                    == "tool"
                ):
                    tool_messages.append(
                        messages[next_index]
                    )

                    next_index += 1

                if len(tool_messages) != len(calls):
                    raise ValueError(
                        (
                            "Invalid Gemini history: "
                            f"expected {len(calls)} tool response(s), "
                            f"received {len(tool_messages)}."
                        ),
                    )

                responses_by_id: dict[
                    str,
                    dict[str, Any],
                ] = {}

                for tool_message in tool_messages:
                    tool_call_id = tool_message.get(
                        "tool_call_id",
                    )

                    if (
                        isinstance(
                            tool_call_id,
                            str,
                        )
                        and tool_call_id
                    ):
                        responses_by_id[
                            tool_call_id
                        ] = tool_message

                response_parts: list[
                    types.Part
                ] = []

                for position, call in enumerate(calls):
                    call_id = call["id"]

                    tool_message = None

                    if call_id:
                        tool_message = (
                            responses_by_id.get(
                                call_id,
                            )
                        )

                    if tool_message is None:
                        tool_message = (
                            tool_messages[position]
                        )

                    response_name = tool_message.get(
                        "name",
                    )

                    if response_name != call["name"]:
                        raise ValueError(
                            (
                                "Invalid Gemini history: "
                                "tool response name does not match "
                                f"function call '{call['name']}'."
                            ),
                        )

                    result = str(
                        tool_message.get(
                            "content",
                            "",
                        )
                        or ""
                    )

                    # =================================================
                    # IMPORTANT:
                    #
                    # Part.from_function_response() does NOT accept
                    # `id` in your installed SDK.
                    #
                    # FunctionResponse DOES support `id`.
                    # =================================================

                    function_response = types.FunctionResponse(
                        id=call_id or None,
                        name=call["name"],
                        response={
                            "result": result,
                        },
                    )

                    response_parts.append(
                        types.Part(
                            function_response=function_response,
                        )
                    )

                # =================================================
                # Your endpoint accepts function responses in
                # a USER content block.
                # =================================================

                contents.append(
                    types.Content(
                        role="user",
                        parts=response_parts,
                    )
                )

                index = next_index
                continue

            # ====================================================
            # ORPHAN TOOL RESULT
            # ====================================================

            if role == "tool":
                raise ValueError(
                    (
                        "Invalid Gemini history: "
                        "orphaned tool response without "
                        "a preceding assistant function call."
                    ),
                )

            raise ValueError(
                f"Unsupported Gemini message role: {role!r}",
            )

        system_instruction = (
            "\n\n".join(system_parts)
            if system_parts
            else None
        )

        return (
            system_instruction,
            contents,
        )

    # ============================================================
    # RESPONSE
    # ============================================================

    @classmethod
    def _convert_response(
        cls,
        response: Any,
    ) -> LLMResponse:
        tool_calls: list[ToolCall] = []

        assistant_message: dict[
            str,
            Any,
        ] = {
            "role": "assistant",
            "content": getattr(
                response,
                "text",
                "",
            )
            or "",
        }

        usage_metadata = getattr(
            response,
            "usage_metadata",
            None,
        )

        usage = (
            cls._usage_from_metadata(
                usage_metadata,
            )
            if usage_metadata is not None
            else None
        )

        candidates = (
            getattr(
                response,
                "candidates",
                None,
            )
            or []
        )

        if not candidates:
            return LLMResponse(
                content=assistant_message["content"],
                tool_calls=[],
                assistant_message=assistant_message,
                usage=usage,
            )

        candidate_content = getattr(
            candidates[0],
            "content",
            None,
        )

        if candidate_content is None:
            return LLMResponse(
                content=assistant_message["content"],
                tool_calls=[],
                assistant_message=assistant_message,
                usage=usage,
            )

        parts = (
            getattr(
                candidate_content,
                "parts",
                None,
            )
            or []
        )

        serialized_calls: list[
            dict[str, Any]
        ] = []

        for index, part in enumerate(parts):
            function_call = getattr(
                part,
                "function_call",
                None,
            )

            if function_call is None:
                continue

            name = getattr(
                function_call,
                "name",
                None,
            )

            if not isinstance(name, str) or not name:
                continue

            arguments = dict(
                getattr(
                    function_call,
                    "args",
                    None,
                )
                or {}
            )

            call_id = getattr(
                function_call,
                "id",
                None,
            )

            if not isinstance(call_id, str) or not call_id:
                call_id = f"gemini-call-{index}"

            tool_calls.append(
                ToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                )
            )

            serialized_call: dict[
                str,
                Any
            ] = {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(
                        arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }

            signature = getattr(
                part,
                "thought_signature",
                None,
            )

            encoded_signature = (
                cls._signature_for_storage(
                    signature,
                )
            )

            if encoded_signature is not None:
                serialized_call[
                    "thought_signature"
                ] = encoded_signature

            serialized_calls.append(
                serialized_call,
            )

        if serialized_calls:
            assistant_message[
                "tool_calls"
            ] = serialized_calls

        return LLMResponse(
            content=assistant_message["content"],
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=usage,
        )

    # ============================================================
    # USAGE
    # ============================================================

    @staticmethod
    def _usage_from_metadata(
        usage_metadata: Any,
    ) -> dict[str, Any]:
        return {
            "input_tokens": getattr(
                usage_metadata,
                "prompt_token_count",
                0,
            ),
            "output_tokens": getattr(
                usage_metadata,
                "candidates_token_count",
                0,
            ),
            "total_tokens": getattr(
                usage_metadata,
                "total_token_count",
                0,
            ),
            "cached_tokens": getattr(
                usage_metadata,
                "cached_content_token_count",
                0,
            ),
            "reasoning_tokens": getattr(
                usage_metadata,
                "thoughts_token_count",
                0,
            ),
        }

    # ============================================================
    # ARGUMENTS
    # ============================================================

    @staticmethod
    def _parse_arguments(
        value: Any,
    ) -> dict[str, Any]:
        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            parsed = json.loads(value)

            if not isinstance(parsed, dict):
                raise TypeError(
                    "Tool arguments must be a JSON object.",
                )

            return parsed

        raise TypeError(
            "Tool arguments must be an object.",
        )

    # ============================================================
    # SIGNATURE STORAGE
    # ============================================================

    @staticmethod
    def _signature_for_storage(
        value: Any,
    ) -> str | None:
        if value is None:
            return None

        if isinstance(value, bytes):
            return base64.urlsafe_b64encode(
                value,
            ).decode("ascii")

        if isinstance(value, str):
            value = value.strip()

            if not value:
                return None

            if GeminiProvider._is_base64(value):
                return value

            try:
                raw = value.encode("latin-1")
            except UnicodeEncodeError:
                return None

            return base64.urlsafe_b64encode(
                raw,
            ).decode("ascii")

        return None

    @staticmethod
    def _decode_signature(
        value: Any,
    ) -> bytes | None:
        if value is None:
            return None

        if isinstance(value, bytes):
            return value

        if not isinstance(value, str):
            return None

        value = value.strip()

        if not value:
            return None

        if GeminiProvider._is_base64(value):
            try:
                padding = "=" * (
                    -len(value) % 4
                )

                return base64.urlsafe_b64decode(
                    value + padding,
                )
            except (
                ValueError,
                binascii.Error,
            ):
                pass

        try:
            return value.encode("latin-1")
        except UnicodeEncodeError:
            return None

    @staticmethod
    def _is_base64(
        value: str,
    ) -> bool:
        try:
            padding = "=" * (
                -len(value) % 4
            )

            decoded = base64.urlsafe_b64decode(
                value + padding,
            )

            return bool(decoded)

        except (
            ValueError,
            binascii.Error,
        ):
            return False

    # ============================================================
    # ERRORS
    # ============================================================

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
                message=(
                    "❌ Gemini rejected the request.\n"
                    f"{exc}"
                ),
                code="invalid_request",
            )

        if code in {401, 403}:
            return LLMProviderError(
                message=(
                    "❌ Gemini authentication/access failed.\n"
                    f"{exc}"
                ),
                code="authentication_error",
            )

        if code == 404:
            return LLMProviderError(
                message=(
                    "❌ Gemini model was not found.\n"
                    f"{exc}"
                ),
                code="model_not_found",
            )

        if code == 429:
            return LLMProviderError(
                message=(
                    "⚠️ Gemini rate limit reached.\n"
                    f"{exc}"
                ),
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
                message=(
                    "⚠️ Gemini is temporarily unavailable.\n"
                    f"{exc}"
                ),
                code="provider_unavailable",
                retryable=True,
            )

        return LLMProviderError(
            message=(
                "❌ Gemini request failed.\n"
                f"{exc}"
            ),
            code="provider_error",
        )