"""Provider registry: factory for creating provider instances."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from ..core.dependencies import get_missing_dependency_warnings
from ..core.errors import ProviderError
from .base import LLMProvider


@dataclass(frozen=True)
class _ProviderSpec:
    module_path: str
    class_name: str


_BUILTIN_PROVIDERS: dict[str, _ProviderSpec] = {
    "anthropic": _ProviderSpec(".anthropic_provider", "AnthropicProvider"),
    "codex": _ProviderSpec(".codex_provider", "CodexProvider"),
    "openai": _ProviderSpec(".openai_provider", "OpenAIProvider"),
    "openai_compat": _ProviderSpec(".openai_compat", "OpenAICompatProvider"),
    "gemini": _ProviderSpec(".gemini_provider", "GeminiProvider"),
    "ollama": _ProviderSpec(".ollama_provider", "OllamaProvider"),
    "minimax": _ProviderSpec(".minimax_provider", "MiniMaxProvider"),
}


class ProviderRegistry:
    """Factory for creating and managing LLM providers."""

    def __init__(self) -> None:
        self._providers: dict[str, _ProviderSpec] = dict(_BUILTIN_PROVIDERS)
        self._provider_classes: dict[str, type[LLMProvider]] = {}
        self._instances: dict[str, LLMProvider] = {}

    def _resolve_provider_class(self, name: str) -> type[LLMProvider]:
        cached = self._provider_classes.get(name)
        if cached is not None:
            return cached

        spec = self._providers.get(name)
        if spec is None:
            raise ProviderError(f"Unknown provider: {name}. Available: {self.list_providers()}")

        try:
            module = importlib.import_module(spec.module_path, package=__package__)
            provider_cls = getattr(module, spec.class_name)
        except (ImportError, AttributeError) as exc:
            raise ProviderError(
                f"Provider '{name}' could not be loaded: {exc}",
                provider=name,
            ) from exc

        self._provider_classes[name] = provider_cls
        return provider_cls

    def register(self, name: str, provider_cls: type[LLMProvider]) -> None:
        self._provider_classes[name] = provider_cls

    def register_custom_providers(self, names: list[str]) -> None:
        """Register custom provider names as OpenAI-compatible endpoints."""
        for name in names:
            if name not in _BUILTIN_PROVIDERS:
                self._providers[name] = _ProviderSpec(".openai_compat", "OpenAICompatProvider")

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    def dependency_warnings(self) -> list[str]:
        """Return user-facing warnings for missing optional runtime packages."""
        return get_missing_dependency_warnings()

    def create(
        self,
        name: str,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> LLMProvider:
        """Create a new provider instance."""
        cls = self._resolve_provider_class(name)

        # Custom OpenAI-compatible providers need their name passed through.
        if name not in _BUILTIN_PROVIDERS:
            kwargs.setdefault("provider_name", name)
            kwargs.setdefault("context_window", int(kwargs.pop("custom_context_window", 128000)))
            kwargs.setdefault("max_output_tokens", int(kwargs.pop("custom_max_output_tokens", 4096)))
            kwargs.setdefault("supports_temperature", bool(kwargs.pop("custom_supports_temperature", True)))
        elif self._providers.get(name) == _BUILTIN_PROVIDERS["openai_compat"] and name != "openai_compat":
            kwargs.setdefault("provider_name", name)

        instance = cls(api_key=api_key, api_base=api_base, model=model, **kwargs)
        self._instances[name] = instance
        return instance

    def get_or_create(
        self,
        name: str,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        **kwargs: Any,
    ) -> LLMProvider:
        """Get existing instance or create new one.

        Recreates the instance if api_key or api_base changed.
        """
        if name in self._instances:
            inst = self._instances[name]
            key_changed = api_key != inst.api_key
            base_changed = api_base != (inst.api_base or "")
            if key_changed or base_changed or (kwargs and name not in _BUILTIN_PROVIDERS):
                return self.create(name, api_key=api_key, api_base=api_base, model=model, **kwargs)
            if model and inst.model != model:
                inst.model = model
            return inst
        return self.create(name, api_key=api_key, api_base=api_base, model=model, **kwargs)

    def get_instance(self, name: str) -> LLMProvider | None:
        return self._instances.get(name)
