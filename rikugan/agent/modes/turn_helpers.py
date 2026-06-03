"""Shared helpers for mode turn execution to avoid boilerplate duplication."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...core.errors import ProviderError
from ...core.types import Message, Role, TokenUsage, ToolResult
from ..turn import TurnEvent

if TYPE_CHECKING:
    from ..loop import AgentLoop


@dataclass
class TurnResult:
    """Outcome of a single agent turn."""

    text: str = ""
    tool_calls: list = field(default_factory=list)
    usage: TokenUsage | None = None
    finish_reason: str | None = None
    cancelled: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.cancelled and self.error is None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


def build_assistant_message(
    assistant_text: str,
    tool_calls: list,
    last_usage: TokenUsage | None,
    raw_parts: list | None,
) -> Message:
    """Build an assistant Message, attaching raw_parts if present."""
    msg = Message(
        role=Role.ASSISTANT,
        content=assistant_text,
        tool_calls=tool_calls,
        token_usage=last_usage,
    )
    if raw_parts is not None:
        msg._raw_parts = raw_parts
    return msg


def finish_reason_notice(finish_reason: str | None) -> str:
    """Return a user-facing notice for non-final provider stop reasons."""
    if not finish_reason:
        return ""
    normalized = finish_reason.lower()
    normal_reasons = {"stop", "end_turn", "tool_calls", "completed", "complete", "success"}
    if normalized in normal_reasons:
        return ""
    if normalized in {"length", "max_tokens", "max_output_tokens", "output_limit"}:
        return (
            "Model output stopped because the provider hit its output token limit. "
            "The answer may be incomplete; ask Rikugan to continue from the last point."
        )
    if normalized in {"content_filter", "safety", "blocked"}:
        return f"Model output stopped early because the provider returned finish_reason={finish_reason!r}."
    return f"Model output stopped with provider finish_reason={finish_reason!r}."


def execute_single_turn(
    loop: AgentLoop,
    system_prompt: str,
    tools_schema: list | None,
) -> Generator[TurnEvent, None, TurnResult]:
    """Execute one LLM turn: stream, store assistant msg, execute tools.

    Yields TurnEvents (text_done, tool progress).  Returns a TurnResult
    so callers can inspect what happened without duplicating the
    stream→store→execute plumbing.
    """
    try:
        (
            assistant_text,
            tool_calls,
            last_usage,
            raw_parts,
            finish_reason,
        ) = yield from loop._stream_llm_turn(system_prompt, tools_schema)
    except ProviderError as e:
        msg = loop._format_provider_error_for_user(e)
        yield TurnEvent.error_event(msg)
        return TurnResult(error=msg)

    if assistant_text:
        yield TurnEvent.text_done(assistant_text)
    notice = finish_reason_notice(finish_reason)
    if notice:
        yield TurnEvent.error_event(notice)

    assistant_msg = build_assistant_message(
        assistant_text,
        tool_calls,
        last_usage,
        raw_parts,
    )
    loop.session.add_message(assistant_msg)

    if not tool_calls:
        return TurnResult(text=assistant_text, usage=last_usage, finish_reason=finish_reason)

    # Execute tools and store results
    tool_results: list[ToolResult] = yield from loop._execute_tool_calls(tool_calls)
    loop.session.add_message(Message(role=Role.TOOL, tool_results=tool_results))

    return TurnResult(
        text=assistant_text,
        tool_calls=tool_calls,
        usage=last_usage,
        finish_reason=finish_reason,
    )
