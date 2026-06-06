"""Function listing, searching, and info tools for Binary Ninja."""

from __future__ import annotations

from itertools import islice
from typing import Annotated

from ...core.logging import log_debug
from ...tools.base import tool
from ...tools.functions import format_function_summary
from .compat import parse_addr_like, require_bv
from .disasm_utils import get_instruction_len
from .fn_utils import (
    get_function_at,
    get_function_end,
    get_function_name,
    iter_function_instruction_addresses,
    iter_functions,
)


def _collect_callers(func) -> list[str]:
    callers = set()
    direct = getattr(func, "callers", None)
    if direct is not None:
        try:
            for c in direct:
                callers.add(get_function_name(c))
        except Exception as e:
            log_debug(f"_collect_callers failed: {e}")
    return sorted(callers)


def _collect_callees(func) -> list[str]:
    callees = set()
    direct = getattr(func, "callees", None)
    if direct is not None:
        try:
            for c in direct:
                callees.add(get_function_name(c))
        except Exception as e:
            log_debug(f"_collect_callees failed: {e}")
    return sorted(callees)


@tool(category="functions")
def list_functions(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max number of functions to return"] = 50,
) -> str:
    """List functions in the binary with pagination."""
    bv = require_bv()
    offset = max(0, int(offset))
    limit = max(1, int(limit))
    page, total = _paged_functions(bv, offset, limit)

    lines = [f"Functions {offset}\u2013{offset + len(page)} of {total}:"]
    for f in page:
        start = int(getattr(f, "start", 0))
        lines.append(f"  0x{start:x}  {get_function_name(f)}")
    return "\n".join(lines)


def _paged_functions(bv, offset: int, limit: int) -> tuple[list, int | str]:
    """Return one function page without copying the whole BN function list."""
    funcs_obj = getattr(bv, "functions", []) or []
    try:
        total: int | str = len(funcs_obj)
    except TypeError:
        total = "unknown"

    try:
        page = list(funcs_obj[offset : offset + limit])
    except TypeError:
        page = list(islice(iter(funcs_obj), offset, offset + limit))

    try:
        page.sort(key=lambda f: int(getattr(f, "start", 0)))
    except Exception as e:
        log_debug(f"Function page sort failed: {e}")
    return page, total


@tool(category="functions")
def get_function_info(address: Annotated[str, "Function address (hex string)"]) -> str:
    """Get detailed information about a specific function."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    start = int(getattr(func, "start", ea))
    end = get_function_end(func)
    size = max(0, end - start)
    blocks = 0
    instrs = 0

    try:
        bbs = list(getattr(func, "basic_blocks", []) or [])
        blocks = len(bbs)
        if blocks:
            for bb in bbs:
                ic = getattr(bb, "instruction_count", None)
                if isinstance(ic, int) and ic >= 0:
                    instrs += ic
                else:
                    cur = int(getattr(bb, "start", 0))
                    bb_end = int(getattr(bb, "end", cur))
                    while cur < bb_end:
                        instrs += 1
                        step = max(1, get_instruction_len(bv, cur))
                        cur += step
        else:
            instrs = len(list(iter_function_instruction_addresses(func)))
    except Exception as e:
        log_debug(f"Basic block analysis failed for 0x{start:x}: {e}")

    callers = _collect_callers(func)[:10]
    callees = _collect_callees(func)[:10]

    return format_function_summary(get_function_name(func), start, end, size, blocks, instrs, callers, callees)


@tool(category="functions")
def search_functions(
    query: Annotated[str, "Search string (substring match on function name)"],
    limit: Annotated[int, "Max results"] = 20,
) -> str:
    """Search for functions by name substring."""
    bv = require_bv()
    q = query.lower()
    results = []
    for func in iter_functions(bv):
        name = get_function_name(func)
        if q in name.lower():
            start = int(getattr(func, "start", 0))
            results.append(f"  0x{start:x}  {name}")
            if len(results) >= limit:
                break
    if not results:
        return f"No functions matching '{query}'"
    return f"Found {len(results)} function(s):\n" + "\n".join(results)
