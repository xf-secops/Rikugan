"""Function listing, searching, and info tools."""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from itertools import islice
from typing import Annotated

from ...core.logging import log_debug
from ...tools.base import parse_addr, tool


def format_function_summary(
    name: str,
    start: int,
    end: int,
    size: int,
    blocks: int,
    instrs: int,
    callers: list[str],
    callees: list[str],
) -> str:
    """Format a function info summary string (shared between IDA and BN tools)."""
    parts = [
        f"Name: {name}",
        f"Address: 0x{start:x} \u2013 0x{end:x}",
        f"Size: {size} bytes",
        f"Basic blocks: {blocks}",
        f"Instructions: {instrs}",
    ]
    if callers:
        parts.append(f"Callers ({len(callers)}): {', '.join(callers)}")
    if callees:
        parts.append(f"Callees ({len(callees)}): {', '.join(callees)}")
    return "\n".join(parts)


try:
    ida_funcs = importlib.import_module("ida_funcs")
    ida_gdl = importlib.import_module("ida_gdl")
    ida_name = importlib.import_module("ida_name")
    idc = importlib.import_module("idc")
    idautils = importlib.import_module("idautils")
except ImportError as e:
    log_debug(f"IDA modules not available: {e}")


@tool(category="functions")
def list_functions(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max number of functions to return"] = 50,
) -> str:
    """List functions in the binary with pagination."""

    offset = max(0, int(offset))
    limit = max(1, int(limit))
    page, total = _paged_function_addresses(offset, limit)

    lines = [f"Functions {offset}\u2013{offset + len(page)} of {total}:"]
    for ea in page:
        name = ida_name.get_name(ea)
        lines.append(f"  0x{ea:x}  {name}")
    return "\n".join(lines)


def _paged_function_addresses(offset: int, limit: int) -> tuple[list[int], int | str]:
    """Return one page of function addresses without materializing all functions."""
    try:
        qty = ida_funcs.get_func_qty()
    except (AttributeError, TypeError):
        qty = None

    if isinstance(qty, int) and qty >= 0:
        end = min(qty, offset + limit)
        page: list[int] = []
        for idx in range(offset, end):
            func = ida_funcs.getn_func(idx)
            if func is not None:
                page.append(int(func.start_ea))
        return page, qty

    funcs: Iterable[int] = iter(idautils.Functions())
    page = [int(ea) for ea in islice(funcs, offset, offset + limit)]
    # Older/test environments may not expose get_func_qty(); count only there.
    total = offset + len(page) + sum(1 for _ in funcs)
    return page, total


@tool(category="functions")
def get_function_info(address: Annotated[str, "Function address (hex string)"]) -> str:
    """Get detailed information about a specific function."""

    ea = parse_addr(address)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    name = ida_name.get_name(func.start_ea)
    size = func.end_ea - func.start_ea
    # Count basic blocks and instructions
    blocks = 0
    instrs = 0
    try:
        fc = ida_gdl.FlowChart(func)
        for block in fc:
            blocks += 1
            head = block.start_ea
            while head < block.end_ea:
                instrs += 1
                head = idc.next_head(head, block.end_ea)
    except Exception as e:
        log_debug(f"FlowChart analysis failed for 0x{ea:x}: {e}")

    # Get callers and callees
    callers = []
    for ref in idautils.CodeRefsTo(func.start_ea, 0):
        caller_func = ida_funcs.get_func(ref)
        if caller_func:
            cname = ida_name.get_name(caller_func.start_ea)
            callers.append(cname)
    callers = list(set(callers))[:10]

    callees = []
    for item in idautils.FuncItems(func.start_ea):
        for ref in idautils.CodeRefsFrom(item, 0):
            callee_func = ida_funcs.get_func(ref)
            if callee_func and callee_func.start_ea != func.start_ea:
                cname = ida_name.get_name(callee_func.start_ea)
                callees.append(cname)
    callees = list(set(callees))[:10]

    return format_function_summary(name, func.start_ea, func.end_ea, size, blocks, instrs, callers, callees)


@tool(category="functions")
def search_functions(
    query: Annotated[str, "Search string (substring match on function name)"],
    limit: Annotated[int, "Max results"] = 20,
) -> str:
    """Search for functions by name substring."""

    results = []
    q = query.lower()
    for ea in idautils.Functions():
        name = ida_name.get_name(ea)
        if q in name.lower():
            results.append(f"  0x{ea:x}  {name}")
            if len(results) >= limit:
                break

    if not results:
        return f"No functions matching '{query}'"
    return f"Found {len(results)} function(s):\n" + "\n".join(results)
