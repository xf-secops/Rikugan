"""Google Gemini provider adapter (google-genai SDK)."""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Generator
from typing import Any, NoReturn

from ..core.errors import (
    AuthenticationError,
    ContextLengthError,
    ProviderError,
    RateLimitError,
)
from ..core.logging import log_debug
from ..core.types import (
    Message,
    ModelInfo,
    ProviderCapabilities,
    Role,
    StreamChunk,
    TokenUsage,
    ToolCall,
)
from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """Adapter for Google Gemini via the google-genai SDK."""

    def __init__(self, api_key: str = "", model: str = "gemini-2.0-flash", **kwargs):
        api_key = api_key or os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        super().__init__(api_key=api_key, model=model)
        self._types: Any = None  # google.genai.types module

    def _get_client(self):
        if self._client is None:
            try:
                genai = importlib.import_module("google.genai")
                self._types = importlib.import_module("google.genai.types")
            except ImportError as exc:
                raise ProviderError(
                    "google-genai package not installed. Run: pip install google-genai",
                    provider="gemini",
                ) from exc
            if not self.api_key:
                raise AuthenticationError(provider="gemini")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tool_use=True,
            vision=True,
            max_context_window=1000000,
            max_output_tokens=8192,
            supports_system_prompt=True,
        )

    def _fetch_models_live(self) -> list[ModelInfo]:
        """Fetch content-generation models from the Gemini API."""
        client = self._get_client()
        models = []
        for m in client.models.list():
            name = m.name
            model_id = name.replace("models/", "") if name.startswith("models/") else name
            display = getattr(m, "display_name", model_id)
            ctx = getattr(m, "input_token_limit", 1000000) or 1000000
            out = getattr(m, "output_token_limit", 8192) or 8192
            models.append(
                ModelInfo(
                    id=model_id,
                    name=display,
                    provider="gemini",
                    context_window=ctx,
                    max_output_tokens=out,
                    supports_tools=True,
                    supports_vision=True,
                )
            )
        models.sort(key=lambda m: m.id, reverse=True)
        return models if models else self._builtin_models()

    @staticmethod
    def _builtin_models() -> list[ModelInfo]:
        return [
            ModelInfo(
                "gemini-3-pro-preview",
                "Gemini 3 Pro Preview",
                "gemini",
                1048576,
                65536,
                True,
                True,
            ),
            ModelInfo(
                "gemini-2.5-pro",
                "Gemini 2.5 Pro",
                "gemini",
                1048576,
                65536,
                True,
                True,
            ),
            ModelInfo(
                "gemini-2.5-flash",
                "Gemini 2.5 Flash",
                "gemini",
                1048576,
                65536,
                True,
                True,
            ),
            ModelInfo(
                "gemini-2.5-flash-lite",
                "Gemini 2.5 Flash-Lite",
                "gemini",
                1048576,
                65536,
                True,
                True,
            ),
            ModelInfo(
                "gemini-2.0-flash",
                "Gemini 2.0 Flash",
                "gemini",
                1048576,
                8192,
                True,
                True,
            ),
        ]

    def _handle_api_error(self, e: Exception) -> NoReturn:
        """Raise the appropriate Rikugan error from a Gemini API error.

        Uses typed exception checks from google.api_core.exceptions when
        available, falling back to string matching for older SDK versions.
        """
        try:
            gexc = importlib.import_module("google.api_core.exceptions")
            if isinstance(e, (gexc.Unauthenticated, gexc.PermissionDenied)):
                raise AuthenticationError(provider="gemini") from e
            if isinstance(e, gexc.ResourceExhausted):
                raise RateLimitError(provider="gemini") from e
            if isinstance(e, gexc.InvalidArgument):
                msg = str(e)
                if "token" in msg.lower() and ("limit" in msg.lower() or "exceed" in msg.lower()):
                    raise ContextLengthError(msg, provider="gemini") from e
        except ImportError as ie:
            log_debug(f"google.api_core.exceptions unavailable, using string matching: {ie}")

        msg = str(e)
        msg_lower = msg.lower()
        if "api key" in msg_lower or "permission" in msg_lower or "unauthenticated" in msg_lower or "401" in msg:
            raise AuthenticationError(provider="gemini") from e
        if "rate limit" in msg_lower or "resource exhausted" in msg_lower or "quota" in msg_lower or "429" in msg:
            raise RateLimitError(provider="gemini") from e
        if "token" in msg_lower and ("limit" in msg_lower or "exceed" in msg_lower):
            raise ContextLengthError(msg, provider="gemini") from e
        raise ProviderError(msg, provider="gemini") from e

    def _build_tools(self, tools: list[dict[str, Any]]) -> list:
        """Convert tool definitions to Gemini function declarations.

        The new google-genai SDK accepts ``parameters_json_schema`` which
        takes a raw JSON Schema dict directly — no type-enum conversion needed.
        """
        types = self._types
        declarations = []
        for t in tools:
            func = t.get("function", t)
            params = func.get("parameters", {})
            declarations.append(
                types.FunctionDeclaration(
                    name=func["name"],
                    description=func.get("description", ""),
                    parameters_json_schema=params if params else None,
                )
            )
        return [types.Tool(function_declarations=declarations)]

    def _format_messages(self, messages: list[Message]) -> list:
        return self._build_contents(messages)

    def _build_contents(self, messages: list[Message]) -> list:
        """Convert messages to a list of ``types.Content`` objects.

        For assistant messages that have ``_raw_parts`` (preserved from a
        previous Gemini response), replay them as-is so ``thought_signature``
        fields are kept intact.  Gemini 2.5+ models require these signatures
        on ``functionCall`` parts; reconstructing from our internal ToolCall
        objects would strip them.
        """
        types = self._types
        contents = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                continue
            elif msg.role == Role.USER:
                text = msg.content if msg.content else "continue"
                contents.append(
                    types.Content(
                        role="user",
                        parts=[types.Part.from_text(text=text)],
                    )
                )
            elif msg.role == Role.ASSISTANT:
                # Prefer raw parts (preserves thought_signatures)
                if getattr(msg, "_raw_parts", None):
                    contents.append(
                        types.Content(
                            role="model",
                            parts=list(msg._raw_parts),
                        )
                    )
                else:
                    parts = []
                    if msg.content:
                        parts.append(types.Part.from_text(text=msg.content))
                    for tc in msg.tool_calls:
                        parts.append(
                            types.Part(
                                function_call=types.FunctionCall(
                                    name=tc.name,
                                    args=tc.arguments,
                                )
                            )
                        )
                    if parts:
                        contents.append(types.Content(role="model", parts=parts))
            elif msg.role == Role.TOOL:
                parts = []
                for tr in msg.tool_results:
                    parts.append(
                        types.Part.from_function_response(
                            name=tr.name,
                            response={"result": tr.content},
                        )
                    )
                if parts:
                    contents.append(types.Content(role="user", parts=parts))
        return contents

    def _build_config(
        self,
        temperature: float,
        max_tokens: int,
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ):
        """Build a ``GenerateContentConfig``."""
        types = self._types
        kwargs: dict[str, Any] = {
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system:
            kwargs["system_instruction"] = system
        if tools:
            kwargs["tools"] = self._build_tools(tools)
            kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        return types.GenerateContentConfig(**kwargs)

    def _build_request_kwargs(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
        system: str,
    ) -> dict[str, Any]:
        """Build kwargs dict for Gemini generate_content / generate_content_stream."""
        return {
            "model": self.model,
            "contents": self._build_contents(messages),
            "config": self._build_config(temperature, max_tokens, system, tools),
        }

    def _call_api(self, client: Any, kwargs: dict[str, Any]) -> Any:
        """Invoke the Gemini generate_content API."""
        return client.models.generate_content(**kwargs)

    def _normalize_response(self, response) -> Message:
        text = ""
        tool_calls = []
        raw_parts = list(response.candidates[0].content.parts)
        for part in raw_parts:
            if part.text:
                if getattr(part, "thought", False):
                    text += f"<think>{part.text}</think>\n"
                else:
                    text += part.text
            if part.function_call:
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=ToolCall.make_id(),
                        name=fc.name,
                        arguments=dict(fc.args) if fc.args else {},
                    )
                )

        usage = TokenUsage()
        if response.usage_metadata:
            um = response.usage_metadata
            usage = TokenUsage(
                prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
                total_tokens=getattr(um, "total_token_count", 0) or 0,
            )

        msg = Message(role=Role.ASSISTANT, content=text, tool_calls=tool_calls, token_usage=usage)
        msg._raw_parts = raw_parts
        return msg

    def _stream_chunks(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Generator[StreamChunk, None, None]:
        """Yield StreamChunks from the Gemini streaming API."""
        try:
            all_raw_parts: list = []
            last_usage: TokenUsage | None = None
            _in_thought = False
            for chunk in client.models.generate_content_stream(**kwargs):
                if not chunk.candidates or not chunk.candidates[0].content:
                    continue
                parts = chunk.candidates[0].content.parts
                if not parts:
                    continue
                for part in parts:
                    all_raw_parts.append(part)
                    if part.text:
                        is_thought = getattr(part, "thought", False)
                        if is_thought and not _in_thought:
                            yield StreamChunk(text="<think>")
                            _in_thought = True
                        elif not is_thought and _in_thought:
                            yield StreamChunk(text="</think>\n")
                            _in_thought = False
                        yield StreamChunk(text=part.text)
                    if part.function_call:
                        fc = part.function_call
                        call_id = ToolCall.make_id()
                        yield StreamChunk(
                            tool_call_id=call_id,
                            tool_name=fc.name,
                            tool_args_delta=json.dumps(dict(fc.args) if fc.args else {}),
                            is_tool_call_start=True,
                        )
                        yield StreamChunk(
                            tool_call_id=call_id,
                            tool_name=fc.name,
                            is_tool_call_end=True,
                        )
                if chunk.usage_metadata:
                    um = chunk.usage_metadata
                    last_usage = TokenUsage(
                        prompt_tokens=getattr(um, "prompt_token_count", 0) or 0,
                        completion_tokens=getattr(um, "candidates_token_count", 0) or 0,
                        total_tokens=getattr(um, "total_token_count", 0) or 0,
                    )
            if _in_thought:
                yield StreamChunk(text="</think>\n")
            yield StreamChunk(
                usage=last_usage or TokenUsage(),
                raw_parts=all_raw_parts if all_raw_parts else None,
            )
        except Exception as e:
            self._handle_api_error(e)
