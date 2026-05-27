"""LLM provider abstract base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any, NoReturn

from ..core.logging import log_debug
from ..core.types import (
    Message,
    ModelInfo,
    ProviderCapabilities,
    StreamChunk,
)


class LLMProvider(ABC):
    """Abstract base for all LLM provider adapters.

    The translation pipeline (format -> build kwargs -> call API -> normalize)
    is implemented once in the concrete ``chat`` and ``chat_stream`` methods.
    Subclasses supply provider-specific hooks:

    * ``_format_messages`` -- convert internal ``Message`` list to wire format
    * ``_build_request_kwargs`` -- assemble the full request dict
    * ``_call_api`` -- invoke the SDK and return the raw response
    * ``_normalize_response`` -- convert the raw response to a ``Message``
    * ``_handle_api_error`` -- translate SDK exceptions to Rikugan errors
    * ``_stream_chunks`` -- yield ``StreamChunk`` objects from the provider stream

    Subclasses must also implement: ``name``, ``capabilities``,
    ``_get_client``, ``_fetch_models_live``, ``_builtin_models``.
    """

    def __init__(self, api_key: str = "", api_base: str = "", model: str = ""):
        self.api_key = api_key
        self.api_base = api_base
        self.model = model
        self._client: Any = None

    # -- Abstract interface ----------------------------------------------------

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g. 'anthropic', 'openai')."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        ...

    @abstractmethod
    def _get_client(self) -> Any:
        """Return the SDK client, creating it lazily if needed."""
        ...

    @abstractmethod
    def _fetch_models_live(self) -> list[ModelInfo]:
        """Fetch models from the remote API. May raise on failure."""
        ...

    @staticmethod
    @abstractmethod
    def _builtin_models() -> list[ModelInfo]:
        """Return built-in fallback model list (no network required)."""
        ...

    # -- Translation pipeline hooks (abstract) ---------------------------------

    @abstractmethod
    def _format_messages(self, messages: list[Message]) -> Any:
        """Convert internal messages to provider wire format."""

    @abstractmethod
    def _build_request_kwargs(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
        system: str,
    ) -> dict[str, Any]:
        """Assemble the full request kwargs for the provider SDK call."""

    @abstractmethod
    def _call_api(self, client: Any, kwargs: dict[str, Any]) -> Any:
        """Invoke the provider SDK and return the raw response object."""

    @abstractmethod
    def _normalize_response(self, raw: Any) -> Message:
        """Convert provider response to internal Message."""

    @abstractmethod
    def _handle_api_error(self, e: Exception) -> NoReturn:
        """Translate a provider SDK exception into a Rikugan error."""

    @abstractmethod
    def _stream_chunks(
        self,
        client: Any,
        kwargs: dict[str, Any],
    ) -> Generator[StreamChunk, None, None]:
        """Yield ``StreamChunk`` objects from the provider's streaming API.

        Receives the same kwargs produced by ``_build_request_kwargs``.
        The implementation may modify *kwargs* (e.g. add ``stream=True``)
        before passing them to the SDK.
        """

    # -- Concrete pipeline implementations -------------------------------------

    def chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str = "",
    ) -> Message:
        """Non-streaming chat completion.

        Orchestrates the standard pipeline:
        get client -> build kwargs -> call API -> normalize response.
        """
        client = self._get_client()
        kwargs = self._build_request_kwargs(messages, tools, system)
        try:
            raw = self._call_api(client, kwargs)
        except Exception as e:
            self._handle_api_error(e)
        return self._normalize_response(raw)

    def chat_stream(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        system: str = "",
    ) -> Generator[StreamChunk, None, None]:
        """Streaming chat completion.

        Builds request kwargs then delegates to ``_stream_chunks`` for the
        provider-specific streaming state machine.
        """
        client = self._get_client()
        kwargs = self._build_request_kwargs(messages, tools, system)
        yield from self._stream_chunks(client, kwargs)

    # -- Concrete shared implementations ---------------------------------------

    def list_models(self) -> list[ModelInfo]:
        """List available models.

        Attempts a live API fetch via ``_fetch_models_live()``.  On any
        failure, logs the error and returns ``_builtin_models()`` so callers
        never see an exception.
        """
        try:
            return self._fetch_models_live()
        except Exception as exc:
            log_debug(f"{self.name} list_models failed, using builtins: {exc}")
            return self._builtin_models()

    def ensure_ready(self) -> None:
        """Pre-initialize the provider (imports, client objects, etc.).

        MUST be called on the main thread before handing the provider to a
        background thread.  Python 3.14 crashes when heavy C-extension
        packages (httpx, h2, ssl ...) are first imported from a non-main
        thread, so providers that lazy-import SDK packages override
        ``_init_client`` to force the import on the caller's thread.
        """
        self._init_client()

    def _init_client(self) -> None:
        """Pre-import SDK and create client. Delegates to ``_get_client()``."""
        self._get_client()

    def auth_status(self) -> tuple[str, str]:
        """Return (label, status_type) describing the current auth state.

        status_type is one of: "ok", "error", "none".
        Subclasses override for provider-specific logic (e.g. OAuth detection).
        """
        if self.api_key:
            return "API Key", "ok"
        return "", "none"

    def context_window(self) -> int:
        """Return the provider/model context window used for trimming."""
        return self.capabilities.max_context_window

    def validate_key(self) -> bool:
        """Probe whether current credentials can reach the API.

        Calls ``_fetch_models_live()`` directly (bypassing the fallback
        in ``list_models()``) so that authentication errors are surfaced
        rather than silently masked by built-in model lists.
        """
        try:
            self._fetch_models_live()
            return True
        except Exception as e:
            log_debug(f"validate_key failed for {self.name}: {e}")
            return False
