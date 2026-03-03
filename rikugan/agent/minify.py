"""Prompt minification: strip unnecessary whitespace to reduce token usage.

All text sent to the LLM passes through `minify_prompt` before hitting the
provider.  The function is intentionally conservative — it removes only
pure-whitespace noise that never carries semantic value:

  - Runs of 3+ blank lines → single blank line
  - Trailing whitespace on each line
  - Leading/trailing blank lines from the whole text

It does NOT collapse indentation (code blocks, markdown lists, etc.) because
that changes meaning.
"""

from __future__ import annotations

import re
from copy import copy
from typing import List

from ..core.types import Message, ToolResult

# 2+ consecutive blank lines (3+ newlines, possibly with whitespace) → single blank line
_MULTI_BLANK_RE = re.compile(r"\n([ \t]*\n){2,}")

# Trailing whitespace on each line
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def minify_text(text: str) -> str:
    """Minify a text string by stripping redundant whitespace."""
    if not text:
        return text
    text = _TRAILING_WS_RE.sub("", text)
    text = _MULTI_BLANK_RE.sub("\n\n", text)
    text = text.strip()
    return text


def minify_messages(messages: List[Message]) -> List[Message]:
    """Return a shallow-copied message list with all text content minified."""
    result: List[Message] = []
    for msg in messages:
        m = copy(msg)
        if m.content:
            m.content = minify_text(m.content)
        if m.tool_results:
            m.tool_results = [
                ToolResult(
                    tool_call_id=tr.tool_call_id,
                    name=tr.name,
                    content=minify_text(tr.content) if tr.content else tr.content,
                    is_error=tr.is_error,
                )
                for tr in m.tool_results
            ]
        result.append(m)
    return result
