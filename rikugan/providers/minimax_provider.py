"""MiniMax provider — Anthropic SDK against MiniMax's compatible API.

MiniMax recommends the Anthropic SDK for integration:
  https://platform.minimax.io/docs/guides/quickstart-sdk

Base URL:  https://api.minimax.io/anthropic
Auth:      plain API key (no OAuth)
"""

from __future__ import annotations

import importlib
from typing import Any

from ..core.errors import AuthenticationError, ProviderError
from ..core.types import ModelInfo, ProviderCapabilities
from .anthropic_provider import AnthropicProvider
from .base import LLMProvider


class MiniMaxProvider(AnthropicProvider):
    """MiniMax LLM provider using the Anthropic-compatible API at api.minimax.io."""

    DEFAULT_API_BASE = "https://api.minimax.io/anthropic"

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "MiniMax-M2.5",
        **kwargs,
    ):
        # Bypass AnthropicProvider.__init__ — MiniMax uses plain API keys only,
        # no OAuth keychain lookup.
        LLMProvider.__init__(
            self,
            api_key=api_key,
            api_base=api_base or self.DEFAULT_API_BASE,
            model=model,
        )
        self._auth_type = "api_key"

    @property
    def name(self) -> str:
        return "minimax"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            streaming=True,
            tool_use=True,
            vision=False,
            max_context_window=204800,
            max_output_tokens=8192,
            supports_system_prompt=True,
            supports_cache_control=False,
        )

    def _get_client(self):
        if self._client is None:
            try:
                anthropic = importlib.import_module("anthropic")
            except ImportError as exc:
                raise ProviderError(
                    "anthropic package not installed. Run: pip install anthropic",
                    provider="minimax",
                ) from exc
            if not self.api_key:
                raise AuthenticationError(provider="minimax")
            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                base_url=self.api_base,
            )
        return self._client

    def auth_status(self):
        if self.api_key:
            return "API Key", "ok"
        return "", "none"

    @staticmethod
    def _builtin_models() -> list[ModelInfo]:
        return [
            ModelInfo(
                id="MiniMax-M2.5",
                name="MiniMax M2.5",
                provider="minimax",
                context_window=204800,
                max_output_tokens=8192,
                supports_tools=True,
            ),
            ModelInfo(
                id="MiniMax-M2.5-highspeed",
                name="MiniMax M2.5 Highspeed",
                provider="minimax",
                context_window=204800,
                max_output_tokens=8192,
                supports_tools=True,
            ),
            ModelInfo(
                id="MiniMax-M2.1",
                name="MiniMax M2.1",
                provider="minimax",
                context_window=204800,
                max_output_tokens=8192,
                supports_tools=True,
            ),
            ModelInfo(
                id="MiniMax-M2.1-highspeed",
                name="MiniMax M2.1 Highspeed",
                provider="minimax",
                context_window=204800,
                max_output_tokens=8192,
                supports_tools=True,
            ),
            ModelInfo(
                id="MiniMax-M2",
                name="MiniMax M2",
                provider="minimax",
                context_window=204800,
                max_output_tokens=8192,
                supports_tools=True,
            ),
        ]

    def _fetch_models_live(self) -> list[ModelInfo]:
        try:
            client = self._get_client()
            response = client.models.list(limit=50)
            models = [
                ModelInfo(
                    id=m.id,
                    name=getattr(m, "display_name", None) or m.id,
                    provider="minimax",
                    context_window=204800,
                    max_output_tokens=8192,
                    supports_tools=True,
                )
                for m in response.data
                if m.id.lower().startswith("minimax")
            ]
            return models or self._builtin_models()
        except Exception:
            return self._builtin_models()

    def _build_request_kwargs(
        self,
        messages,
        tools: list[dict[str, Any]] | None,
        system: str,
    ) -> dict[str, Any]:
        """Build request kwargs, stripping cache_control (not supported by MiniMax)."""
        kwargs = super()._build_request_kwargs(messages, tools, system)

        # System prompt: strip cache_control from blocks
        if isinstance(kwargs.get("system"), list):
            for block in kwargs["system"]:
                block.pop("cache_control", None)
            # If only one plain text block, collapse to a string
            if len(kwargs["system"]) == 1 and kwargs["system"][0].get("type") == "text":
                kwargs["system"] = kwargs["system"][0]["text"]

        # Messages: strip cache_control from content blocks
        for msg in kwargs.get("messages", []):
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        block.pop("cache_control", None)

        # Tools: strip cache_control
        for tool in kwargs.get("tools", []):
            if isinstance(tool, dict):
                tool.pop("cache_control", None)

        return kwargs
