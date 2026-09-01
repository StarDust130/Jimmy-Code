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
    """Google Gemini provider for Jimmy."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-3.5-flash-lite",
        timeout_ms: int = 180_000,  # 180 seconds
    ) -> None:
        self.model = model

        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
            ),
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str | LLMResponse]:
        """
        Stream Gemini output as real provider chunks.

        Contract used by AgentTurn:
          * yield text deltas as plain strings immediately
          * yield one final LLMResponse after the stream finishes

        Tool calls are collected during streaming and returned only in the
        final LLMResponse. This prevents partial tool arguments from being
        executed and keeps the normal agent/tool loop unchanged.
        """
        system_instruction, contents = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=self._convert_tools(tools) or None,
        )

        text_parts: list[str] = []
        tool_records: dict[tuple[str, int], dict[str, Any]] = {}
        usage: dict[str, Any] | None = None

        try:
            stream = self.client.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config,
            )

            for chunk in stream:
                text = getattr(chunk, "text", None)
                if isinstance(text, str) and text:
                    text_parts.append(text)
                    yield text

                usage_metadata = getattr(
                    chunk,
                    "usage_metadata",
                    None,
                )
                if usage_metadata is not None:
                    usage = self._usage_from_metadata(usage_metadata)

                candidates = (
                    getattr(
                        chunk,
                        "candidates",
                        None,
                    )
                    or []
                )

                for candidate in candidates:
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

                        record_key = (name, index)
                        record = tool_records.setdefault(
                            record_key,
                            {
                                "name": name,
                                "id": None,
                                "arguments": {},
                                "thought_signature": None,
                            },
                        )

                        function_call_id = getattr(
                            function_call,
                            "id",
                            None,
                        )
                        if isinstance(function_call_id, str) and function_call_id:
                            record["id"] = function_call_id

                        arguments = dict(
                            getattr(
                                function_call,
                                "args",
                                None,
                            )
                            or {}
                        )

                        # Merge arguments across streamed chunks. Most Gemini
                        # responses provide the complete object in one chunk,
                        # but merging also handles incremental providers safely.
                        record["arguments"].update(arguments)

                        raw_signature = getattr(
                            part,
                            "thought_signature",
                            None,
                        )
                        if raw_signature is not None:
                            encoded_signature = self._signature_for_storage(raw_signature)
                            if encoded_signature is not None:
                                record["thought_signature"] = encoded_signature

        except errors.APIError as exc:
            raise self._normalize_error(exc) from exc
        except Exception as exc:
            raise LLMProviderError(
                message=(f"❌ Gemini streaming request failed.\n{exc}"),
                code="provider_error",
            ) from exc

        content = "".join(text_parts)

        tool_calls: list[ToolCall] = []
        serialized_tool_calls: list[dict[str, Any]] = []

        for index, record in enumerate(tool_records.values()):
            tool_call_id = record["id"] or f"gemini-call-{index}"
            arguments = dict(record["arguments"] or {})

            call = ToolCall(
                id=tool_call_id,
                name=record["name"],
                arguments=arguments,
            )
            tool_calls.append(call)

            serialized_call: dict[str, Any] = {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": record["name"],
                    "arguments": json.dumps(arguments),
                },
            }

            signature = record.get("thought_signature")
            if signature is not None:
                serialized_call["thought_signature"] = signature

            serialized_tool_calls.append(serialized_call)

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
        }

        if serialized_tool_calls:
            assistant_message["tool_calls"] = serialized_tool_calls

        yield LLMResponse(
            content=content,
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=usage,
        )

    @staticmethod
    def _usage_from_metadata(usage_metadata: Any) -> dict[str, Any]:
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
            function = tool["function"]

            declarations.append(
                {
                    "name": function["name"],
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
                }
            )

        # Use model_validate instead of passing
        # function_declarations as a constructor keyword.
        # This avoids the Pylance issue while producing
        # the same Gemini Tool structure.
        return [
            types.Tool.model_validate(
                {
                    "function_declarations": declarations,
                }
            )
        ]

    # ============================================================
    # MESSAGES
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
        Convert Jimmy's provider-neutral history into Gemini history.

        Gemini requires a strict function-calling sequence:

            model(function_call)
            user(function_response)
            model(...)

        Therefore tool responses are only emitted immediately after the
        assistant/model message that contains the corresponding tool calls.

        System messages become Gemini's system_instruction and are not placed
        inside the conversational content stream.
        """

        system_parts: list[str] = []
        contents: list[types.Content] = []

        index = 0

        while index < len(messages):
            message = messages[index]

            role = message.get("role")
            content = message.get(
                "content",
                "",
            )

            # ======================================================
            # SYSTEM
            # ======================================================

            if role == "system":
                if content:
                    system_parts.append(
                        str(content),
                    )

                index += 1
                continue

            # ======================================================
            # USER
            # ======================================================

            if role == "user":
                if content:
                    contents.append(
                        types.Content.model_validate(
                            {
                                "role": "user",
                                "parts": [
                                    {
                                        "text": str(content),
                                    }
                                ],
                            }
                        )
                    )

                index += 1
                continue

            # ======================================================
            # ASSISTANT / MODEL
            # ======================================================

            if role == "assistant":
                parts: list[types.Part] = []

                if content:
                    parts.append(
                        types.Part.model_validate(
                            {
                                "text": str(content),
                            }
                        )
                    )

                tool_calls = message.get(
                    "tool_calls",
                    [],
                )

                if not isinstance(
                    tool_calls,
                    list,
                ):
                    tool_calls = []

                for call in tool_calls:
                    if not isinstance(
                        call,
                        dict,
                    ):
                        continue

                    function = call.get(
                        "function",
                        {},
                    )

                    if not isinstance(
                        function,
                        dict,
                    ):
                        continue

                    name = function.get(
                        "name",
                    )

                    if (
                        not isinstance(name, str)
                        or not name
                    ):
                        continue

                    arguments = cls._parse_arguments(
                        function.get(
                            "arguments",
                            {},
                        )
                    )

                    part_data: dict[str, Any] = {
                        "function_call": {
                            "name": name,
                            "args": arguments,
                        }
                    }

                    signature = cls._decode_signature(
                        call.get(
                            "thought_signature",
                        )
                    )

                    if signature is not None:
                        part_data[
                            "thought_signature"
                        ] = signature

                    parts.append(
                        types.Part.model_validate(
                            part_data,
                        )
                    )

                if parts:
                    contents.append(
                        types.Content.model_validate(
                            {
                                "role": "model",
                                "parts": parts,
                            }
                        )
                    )

                # --------------------------------------------------
                # If this assistant message contains tool calls,
                # the following messages MUST be tool responses.
                # --------------------------------------------------

                if tool_calls:
                    response_parts: list[types.Part] = []

                    next_index = index + 1

                    while next_index < len(messages):
                        next_message = messages[next_index]

                        if next_message.get("role") != "tool":
                            break

                        tool_name = next_message.get(
                            "name",
                        )

                        if (
                            not isinstance(
                                tool_name,
                                str,
                            )
                            or not tool_name
                        ):
                            raise ValueError(
                                "Invalid Gemini tool history: "
                                "tool response is missing its tool name."
                            )

                        response_content = str(
                            next_message.get(
                                "content",
                                "",
                            )
                            or ""
                        )

                        response_parts.append(
                            types.Part.model_validate(
                                {
                                    "function_response": {
                                        "name": tool_name,
                                        "response": {
                                            "result": response_content,
                                        },
                                    }
                                }
                            )
                        )

                        next_index += 1

                    # --------------------------------------------------
                    # Gemini must receive at least one response for
                    # the function-call turn.
                    # --------------------------------------------------

                    if not response_parts:
                        raise ValueError(
                            "Invalid Gemini tool history: "
                            "a model function-call turn has no "
                            "immediately following tool response."
                        )

                    contents.append(
                        types.Content.model_validate(
                            {
                                "role": "user",
                                "parts": response_parts,
                            }
                        )
                    )

                    index = next_index
                    continue

                index += 1
                continue

            # ======================================================
            # TOOL WITHOUT A PRECEDING ASSISTANT FUNCTION CALL
            # ======================================================

            if role == "tool":
                raise ValueError(
                    "Invalid Gemini tool history: "
                    "orphaned tool response without a preceding "
                    "assistant function-call turn."
                )

            # ======================================================
            # UNKNOWN ROLE
            # ======================================================

            raise ValueError(
                f"Unsupported message role for Gemini: {role!r}",
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

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": response.text or "",
        }

        usage_metadata = getattr(
            response,
            "usage_metadata",
            None,
        )

        usage: dict[str, Any] | None = (
            cls._usage_from_metadata(usage_metadata) if usage_metadata is not None else None
        )

        candidates = getattr(
            response,
            "candidates",
            None,
        )

        if not candidates:
            return LLMResponse(
                content=response.text or "",
                tool_calls=[],
                assistant_message=assistant_message,
                usage=usage,
            )

        candidate = candidates[0]

        candidate_content = getattr(
            candidate,
            "content",
            None,
        )

        if candidate_content is None:
            return LLMResponse(
                content=response.text or "",
                tool_calls=[],
                assistant_message=assistant_message,
                usage=usage,
            )

        response_parts = (
            getattr(
                candidate_content,
                "parts",
                None,
            )
            or []
        )

        serialized_tool_calls: list[dict[str, Any]] = []

        for index, part in enumerate(response_parts):
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

            if (
                not isinstance(
                    name,
                    str,
                )
                or not name
            ):
                continue

            arguments = dict(
                getattr(
                    function_call,
                    "args",
                    None,
                )
                or {}
            )

            tool_call_id = (
                getattr(
                    function_call,
                    "id",
                    None,
                )
                or f"gemini-call-{index}"
            )

            tool_calls.append(
                ToolCall(
                    id=tool_call_id,
                    name=name,
                    arguments=arguments,
                )
            )

            serialized_call: dict[str, Any] = {
                "id": tool_call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }

            raw_signature = getattr(
                part,
                "thought_signature",
                None,
            )

            encoded_signature = cls._signature_for_storage(raw_signature)

            if encoded_signature is not None:
                serialized_call["thought_signature"] = encoded_signature

            serialized_tool_calls.append(serialized_call)

        if serialized_tool_calls:
            assistant_message["tool_calls"] = serialized_tool_calls

        return LLMResponse(
            content=response.text or "",
            tool_calls=tool_calls,
            assistant_message=assistant_message,
            usage=usage,
        )

    # ARGUMENTS
    # ============================================================

    @staticmethod
    def _parse_arguments(
        value: Any,
    ) -> dict[str, Any]:
        if isinstance(
            value,
            dict,
        ):
            return value

        if isinstance(
            value,
            str,
        ):
            parsed = json.loads(value)

            if not isinstance(
                parsed,
                dict,
            ):
                raise TypeError("Tool arguments must be a JSON object.")

            return parsed

        raise TypeError("Tool arguments must be an object.")

    # ============================================================
    # THOUGHT SIGNATURES
    # ============================================================

    @staticmethod
    def _signature_for_storage(
        value: Any,
    ) -> str | None:
        """
        Convert Gemini's signature to JSON-safe text.

        Gemini's Python SDK may expose the signature as bytes.
        Session history is JSON, so store base64 text.
        """

        if value is None:
            return None

        if isinstance(
            value,
            bytes,
        ):
            return base64.urlsafe_b64encode(value).decode("ascii")

        if isinstance(
            value,
            str,
        ):
            # Already encoded correctly.
            if GeminiProvider._is_base64(value):
                return value

            # Some old Jimmy sessions may contain
            # raw bytes decoded as Latin-1 text.
            try:
                raw = value.encode("latin-1")

                if raw:
                    return base64.urlsafe_b64encode(raw).decode("ascii")

            except UnicodeEncodeError:
                pass

        return None

    @staticmethod
    def _decode_signature(
        value: Any,
    ) -> bytes | None:
        """
        Restore a persisted signature.

        Handles:
        - new base64 strings
        - bytes
        - old raw Latin-1 strings

        Invalid legacy data is ignored instead of
        crashing the entire conversation.
        """

        if value is None:
            return None

        if isinstance(
            value,
            bytes,
        ):
            return value

        if not isinstance(
            value,
            str,
        ):
            return None

        value = value.strip()

        if not value:
            return None

        # Normal persisted representation.
        if GeminiProvider._is_base64(value):
            try:
                padding = "=" * (-len(value) % 4)

                return base64.urlsafe_b64decode(value + padding)

            except (
                ValueError,
                binascii.Error,
            ):
                pass

        # Legacy Jimmy representation:
        # raw bytes were accidentally decoded into
        # a Python string. Try to recover them.
        try:
            raw = value.encode("latin-1")

            if raw:
                return raw

        except UnicodeEncodeError:
            pass

        return None

    @staticmethod
    def _is_base64(
        value: str,
    ) -> bool:
        if not value:
            return False

        try:
            padding = "=" * (-len(value) % 4)

            decoded = base64.urlsafe_b64decode(value + padding)

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
