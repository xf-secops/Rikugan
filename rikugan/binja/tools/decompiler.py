"""Decompiler-like tools for Binary Ninja (HLIL based)."""

from __future__ import annotations

from typing import Annotated

from ...core.logging import log_debug
from ...tools.base import tool
from ...tools.pagination import format_page, normalize_page
from .compat import parse_addr_like, require_bv
from .fn_utils import get_function_at


def _get_hlil(func):
    for attr in ("hlil", "high_level_il"):
        try:
            hlil = getattr(func, attr)
            if hlil is not None:
                return hlil
        except Exception as e:
            log_debug(f"_get_hlil {attr} failed: {e}")
            continue
    return None


def _render_hlil(hlil, with_line_numbers: bool = False) -> str:
    lines = []
    instructions = getattr(hlil, "instructions", None)
    if instructions is None:
        text = str(hlil)
        if text:
            return text
        return ""

    for i, ins in enumerate(list(instructions)):
        line = str(ins)
        if with_line_numbers:
            lines.append(f"{i + 1:4d}  {line}")
        else:
            lines.append(line)
    return "\n".join(lines)


@tool(category="decompiler", requires_decompiler=True)
def decompile_function(
    address: Annotated[str, "Function address (hex string)"],
    offset: Annotated[int, "Start pseudocode line for pagination"] = 0,
    limit: Annotated[int, "Max pseudocode lines to return"] = 160,
    with_line_numbers: Annotated[bool, "Include pseudocode line numbers"] = True,
) -> str:
    """Decompile the function at the given address and return paginated pseudocode."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    hlil = _get_hlil(func)
    if hlil is None:
        return f"HLIL not available for function at 0x{int(getattr(func, 'start', ea)):x}"
    text = _render_hlil(hlil, with_line_numbers=bool(with_line_numbers))
    rows = text.splitlines() if text else []
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=f"Pseudocode for 0x{int(getattr(func, 'start', ea)):x}",
        empty="  (no pseudocode)",
        next_hint=f"Call decompile_function with offset={next_offset} limit={page_limit}.",
    )


def get_pseudocode(
    address: Annotated[str, "Function address (hex string)"],
    with_line_numbers: Annotated[bool, "Include line numbers"] = True,
) -> str:
    """Compatibility helper: get HLIL text without registering a second tool."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    hlil = _get_hlil(func)
    if hlil is None:
        return f"HLIL not available for function at 0x{int(getattr(func, 'start', ea)):x}"
    text = _render_hlil(hlil, with_line_numbers=bool(with_line_numbers))
    return text or "(no pseudocode)"


@tool(category="decompiler", requires_decompiler=True)
def get_decompiler_variables(
    address: Annotated[str, "Function address (hex string)"],
) -> str:
    """List local variables from the HLIL output."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    vars_obj = getattr(func, "vars", None)
    if vars_obj is None:
        hlil = _get_hlil(func)
        vars_obj = getattr(hlil, "vars", None) if hlil is not None else None

    lines = ["Local variables:"]
    if vars_obj is None:
        lines.append("  (unavailable)")
        return "\n".join(lines)

    for v in list(vars_obj):
        name = getattr(v, "name", None) or str(v)
        t = getattr(v, "type", None)
        if callable(t):
            try:
                t = t()
            except Exception:
                t = None
        tname = str(t) if t is not None else "?"
        source_type = getattr(v, "source_type", None)
        kind = str(source_type) if source_type is not None else "local"
        lines.append(f"  {kind:8s} {tname:20s} {name}")

    return "\n".join(lines)
