"""Hex-Rays decompiler tools."""

from __future__ import annotations

import importlib
from typing import Annotated

from ...core.errors import ToolError
from ...core.host import HAS_HEXRAYS as _HAS_HEXRAYS
from ...core.logging import log_debug
from ...tools.base import parse_addr, tool
from ...tools.pagination import format_page, normalize_page

ida_hexrays = ida_lines = ida_funcs = ida_idaapi = None
try:
    ida_hexrays = importlib.import_module("ida_hexrays")
    ida_lines = importlib.import_module("ida_lines")
    ida_funcs = importlib.import_module("ida_funcs")
    ida_idaapi = importlib.import_module("ida_idaapi")
except ImportError:
    log_debug("Hex-Rays modules not available — decompiler tools will be disabled")

_BADADDR = 0xFFFFFFFF  # fallback if ida_idaapi not loaded


def _decompile(ea: int):
    """Decompile at *ea*, returning the cfunc_t or a user-facing error string."""
    if not _HAS_HEXRAYS:
        raise ToolError("Hex-Rays decompiler is not available", tool_name="decompiler")
    try:
        cfunc = ida_hexrays.decompile(ea)
    except ida_hexrays.DecompilationFailure as e:
        return f"Decompilation failed at 0x{ea:x}: {e}"
    if cfunc is None:
        return f"Decompilation returned None for 0x{ea:x}"
    return cfunc


@tool(category="decompiler", requires_decompiler=True)
def decompile_function(
    address: Annotated[str, "Function address (hex string)"],
    offset: Annotated[int, "Start pseudocode line for pagination"] = 0,
    limit: Annotated[int, "Max pseudocode lines to return"] = 160,
    with_line_numbers: Annotated[bool, "Include pseudocode line numbers"] = True,
) -> str:
    """Decompile the function at the given address and return paginated pseudocode."""
    result = _decompile(parse_addr(address))
    if isinstance(result, str):
        return result

    rows = _render_pseudocode_lines(result, with_line_numbers=bool(with_line_numbers))
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=f"Pseudocode for 0x{parse_addr(address):x}",
        next_hint=f"Call decompile_function with offset={next_offset} limit={page_limit}.",
    )


def _render_pseudocode_lines(cfunc, with_line_numbers: bool = True) -> list[str]:
    lines = []
    sv = cfunc.get_pseudocode()
    for i, sl in enumerate(sv):
        text = ida_lines.tag_remove(sl.line)
        if with_line_numbers:
            lines.append(f"{i + 1:4d}  {text}")
        else:
            lines.append(text)
    return lines


def get_pseudocode(
    address: Annotated[str, "Function address (hex string)"],
    with_line_numbers: Annotated[bool, "Include line numbers"] = True,
) -> str:
    """Compatibility helper: get pseudocode text without registering a second tool."""
    result = _decompile(parse_addr(address))
    if isinstance(result, str):
        return result

    return "\n".join(_render_pseudocode_lines(result, with_line_numbers=bool(with_line_numbers)))


@tool(category="decompiler", requires_decompiler=True)
def get_decompiler_variables(
    address: Annotated[str, "Function address (hex string)"],
) -> str:
    """List local variables from the decompiler output."""
    result = _decompile(parse_addr(address))
    if isinstance(result, str):
        return result

    lines = ["Local variables:"]
    lvars = result.get_lvars()
    for lv in lvars:
        kind = "arg" if lv.is_arg_var else "local"
        tname = str(lv.type()) if lv.type() else "?"
        lines.append(f"  {kind:5s} {tname:20s} {lv.name}")

    return "\n".join(lines)


def _resolve_ctree_ea(cfunc, target_ea: int):
    """Resolve *target_ea* to an ``(ea, itp)`` pair suitable for ``treeloc_t``.

    Strategy:
    1. Check ``cfunc.eamap`` — the authoritative instruction→ctree mapping.
       If *target_ea* maps to ctree items, use the first statement-level item.
    2. Walk the ctree collecting all statement ``ea`` values and pick the
       nearest one at or before *target_ea* (handles addresses that fall
       inside a compound statement).
    3. Return *None* if nothing matches.
    """
    itp = ida_hexrays.ITP_SEMI

    # --- Strategy 1: eamap lookup ---
    try:
        eamap = cfunc.get_eamap()
        if target_ea in eamap:
            items = eamap[target_ea]
            for item in items:
                if item.is_cinsn():
                    return item.ea, itp
            # No statement — use the first item's ea
            if items:
                return items[0].ea, itp
    except Exception as exc:
        log_debug(f"eamap lookup failed for {target_ea:#x}, falling back to ctree walk: {exc}")

    # --- Strategy 2: nearest statement by ctree walk ---
    stmt_eas = []

    class _Collector(ida_hexrays.ctree_visitor_t):
        def __init__(self):
            super().__init__(ida_hexrays.CV_FAST)

        def visit_insn(self, ins):
            if ins.ea != (ida_idaapi.BADADDR if ida_idaapi else _BADADDR):
                stmt_eas.append(ins.ea)
            return 0

    v = _Collector()
    v.apply_to(cfunc.body, None)

    if not stmt_eas:
        return None

    # Exact match first
    if target_ea in stmt_eas:
        return target_ea, itp

    # Nearest statement at or before target_ea
    candidates = [ea for ea in stmt_eas if ea <= target_ea]
    if candidates:
        return max(candidates), itp

    # Fall back to the closest statement overall
    stmt_eas.sort(key=lambda ea: abs(ea - target_ea))
    return stmt_eas[0], itp


@tool(category="decompiler", requires_decompiler=True, mutating=True)
def set_pseudocode_comment(
    func_address: Annotated[str, "Function address (hex string)"],
    target_address: Annotated[str, "Address of the pseudocode line to comment (hex string)"],
    comment: Annotated[str, "Comment text to insert above the line"],
) -> str:
    """Insert a comment into the Hex-Rays pseudocode view at a specific line.

    The comment appears above the pseudocode line corresponding to
    *target_address* inside the function at *func_address*.  Use this to
    document routines, annotate blocks, or explain specific operations
    directly in the decompiled output.
    """
    func_ea = parse_addr(func_address)
    target_ea = parse_addr(target_address)

    result = _decompile(func_ea)
    if isinstance(result, str):
        return result
    cfunc = result

    func = ida_funcs.get_func(func_ea)
    if func and not (func.start_ea <= target_ea < func.end_ea):
        return f"Address 0x{target_ea:x} is outside function 0x{func.start_ea:x}\u20130x{func.end_ea:x}"

    # Resolve to a valid ctree location; fall back to raw ea + ITP_SEMI
    resolved = _resolve_ctree_ea(cfunc, target_ea)
    item_ea, itp = resolved if resolved else (target_ea, ida_hexrays.ITP_SEMI)

    tl = ida_hexrays.treeloc_t()
    tl.ea = item_ea
    tl.itp = itp

    cfunc.set_user_cmt(tl, comment)
    cfunc.save_user_cmts()

    return f"Set pseudocode comment at 0x{item_ea:x} in function 0x{func_ea:x}:\n{comment}"


@tool(category="decompiler", requires_decompiler=True)
def get_pseudocode_comment(
    func_address: Annotated[str, "Function address (hex string)"],
    target_address: Annotated[str, "Address of the pseudocode line (hex string)"],
) -> str:
    """Read the Hex-Rays pseudocode comment at a specific line.

    Returns the raw comment text, or an empty string if none exists.
    """
    func_ea = parse_addr(func_address)
    target_ea = parse_addr(target_address)

    result = _decompile(func_ea)
    if isinstance(result, str):
        return result
    cfunc = result

    # Resolve through the ctree for consistency with set_pseudocode_comment
    resolved = _resolve_ctree_ea(cfunc, target_ea)
    item_ea, itp = resolved if resolved else (target_ea, ida_hexrays.ITP_SEMI)

    tl = ida_hexrays.treeloc_t()
    tl.ea = item_ea
    tl.itp = itp

    cmt = cfunc.get_user_cmt(tl, ida_hexrays.RETRIEVE_ALWAYS)
    return cmt if cmt else ""
