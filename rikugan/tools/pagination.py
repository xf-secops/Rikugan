"""Shared pagination helpers for user-facing tool output."""

from __future__ import annotations

from collections.abc import Sequence

DEFAULT_PAGE_LIMIT = 80
MAX_PAGE_LIMIT = 200


def normalize_page(offset: int = 0, limit: int = DEFAULT_PAGE_LIMIT) -> tuple[int, int]:
    """Clamp pagination inputs to stable, bounded values."""
    offset = max(0, int(offset))
    limit = max(1, min(int(limit), MAX_PAGE_LIMIT))
    return offset, limit


def format_page(
    rows: Sequence[str],
    *,
    offset: int = 0,
    limit: int = DEFAULT_PAGE_LIMIT,
    title: str,
    empty: str = "  (none)",
    next_hint: str = "",
) -> str:
    """Format a page of already-rendered rows with a continuation hint."""
    offset, limit = normalize_page(offset, limit)
    total = len(rows)
    page = list(rows[offset : offset + limit])
    lines = [f"{title} {offset}-{offset + len(page)} of {total}:"]
    lines.extend(page or [empty])
    next_offset = offset + len(page)
    if next_offset < total:
        hint = next_hint or f"Use offset={next_offset} limit={limit} for the next page."
        lines.append(f"  ... {total - next_offset} more. {hint}")
    return "\n".join(lines)
