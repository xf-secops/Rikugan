"""Context window management: token tracking and compaction."""

from __future__ import annotations

from typing import List, Optional

from ..core.types import Message, Role, TokenUsage
from ..core.logging import log_info


class ContextWindowManager:
    """Tracks token usage and compacts the conversation when approaching limits."""

    def __init__(self, max_tokens: int = 128000, compaction_threshold: float = 0.8):
        self.max_tokens = max_tokens
        self.compaction_threshold = compaction_threshold
        self._total_tokens = 0

    @property
    def usage_ratio(self) -> float:
        if self.max_tokens <= 0:
            return 0
        return self._total_tokens / self.max_tokens

    @property
    def is_near_limit(self) -> bool:
        return self.usage_ratio >= self.compaction_threshold

    def update_usage(self, usage: TokenUsage) -> None:
        # Use prompt_tokens as primary metric — it reflects how much of the
        # context window the conversation occupies.  Fall back to total_tokens
        # if prompt_tokens is unavailable (e.g. non-Anthropic providers).
        effective = usage.prompt_tokens or usage.total_tokens
        # Only update if we get a meaningful value (avoid zeroing out from
        # partial streaming chunks that report total_tokens=0).
        if effective > 0:
            self._total_tokens = effective

    def should_compact(self) -> bool:
        return self.is_near_limit

    def compact_messages(self, messages: List[Message]) -> List[Message]:
        """Compact the message list to reduce token usage.

        Strategy:
        1. Keep the first (system) message
        2. Keep the last N exchanges
        3. Summarize older messages into a single summary message
        """
        if len(messages) <= 6:
            return messages

        # Keep first message and last 4 messages
        keep_tail = 4
        head = messages[:1]  # system/first message
        tail = messages[-keep_tail:]
        middle = messages[1:-keep_tail]

        if not middle:
            return messages

        # Build summary of middle messages
        summary_parts = ["[Context summary of earlier conversation:]"]
        for msg in middle:
            if msg.role == Role.USER:
                summary_parts.append(f"User asked: {msg.content[:100]}...")
            elif msg.role == Role.ASSISTANT:
                text = msg.content[:150] if msg.content else ""
                tool_names = [tc.name for tc in msg.tool_calls]
                if tool_names:
                    summary_parts.append(f"Assistant used tools: {', '.join(tool_names)}")
                if text:
                    summary_parts.append(f"Assistant said: {text}...")
            elif msg.role == Role.TOOL:
                for tr in msg.tool_results:
                    status = "error" if tr.is_error else "success"
                    summary_parts.append(f"Tool {tr.name}: {status}")

        summary_text = "\n".join(summary_parts)
        summary_msg = Message(role=Role.USER, content=summary_text)

        compacted = head + [summary_msg] + tail
        log_info(
            f"Context compacted: {len(messages)} → {len(compacted)} messages "
            f"({len(middle)} messages summarized)"
        )
        return compacted

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """Estimate token count from text length.

        Uses a ~3.5 chars/token ratio based on empirical measurements of
        English prose with GPT-4/Claude tokenizers.  This overestimates
        slightly, which is the safe direction for context window checks
        (better to compact too early than hit the limit).

        For exact counts, a proper tokenizer (tiktoken for OpenAI,
        Anthropic's tokenizer) would be needed, but the added dependency
        and latency are not justified for the compaction heuristic.
        """
        if not text:
            return 0
        # ~3.5 chars/token for English text; multiply by 10/35 to avoid float
        return max(1, len(text) * 10 // 35)
