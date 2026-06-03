"""Cross-reference tools for Binary Ninja."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from ...core.logging import log_debug
from ...tools.base import tool
from ...tools.pagination import format_page, normalize_page
from ...tools.xrefs import format_callers_callees
from .compat import parse_addr_like, require_bv
from .fn_utils import get_function_at, get_function_name
from .sym_utils import resolve_name_at


def _code_refs_to(bv, ea: int) -> Iterable[tuple[int, str, str]]:
    get_refs = getattr(bv, "get_code_refs", None)
    if not callable(get_refs):
        return []
    refs = []
    try:
        refs = list(get_refs(ea))
    except Exception:
        refs = []

    out = []
    for r in refs:
        src = getattr(r, "address", None)
        if not isinstance(src, int):
            continue
        func = get_function_at(bv, src)
        fname = get_function_name(func) if func is not None else "?"
        out.append((src, "code", fname))
    return out


def _data_refs_to(bv, ea: int) -> Iterable[tuple[int, str, str]]:
    get_refs = getattr(bv, "get_data_refs", None)
    if not callable(get_refs):
        return []
    refs = []
    try:
        refs = list(get_refs(ea))
    except Exception:
        refs = []
    out = []
    for src in refs:
        if not isinstance(src, int):
            continue
        func = get_function_at(bv, src)
        fname = get_function_name(func) if func is not None else "?"
        out.append((src, "data", fname))
    return out


def _refs_from(bv, ea: int) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    get_code = getattr(bv, "get_code_refs_from", None)
    if callable(get_code):
        try:
            for dst in list(get_code(ea)):
                if isinstance(dst, int):
                    out.append((dst, "code"))
                else:
                    d = getattr(dst, "target", None)
                    if isinstance(d, int):
                        out.append((d, "code"))
        except Exception as e:
            log_debug(f"_iter_refs_from get_code_refs_from failed at 0x{ea:x}: {e}")

    get_data = getattr(bv, "get_data_refs_from", None)
    if callable(get_data):
        try:
            for dst in list(get_data(ea)):
                if isinstance(dst, int):
                    out.append((dst, "data"))
        except Exception as e:
            log_debug(f"_iter_refs_from get_data_refs_from failed at 0x{ea:x}: {e}")
    return out


@tool(category="xrefs")
def xrefs_to(
    address: Annotated[str, "Target address (hex string)"],
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max results"] = 30,
) -> str:
    """Get cross-references to the given address with pagination."""
    bv = require_bv()
    ea = parse_addr_like(address)
    target_name = resolve_name_at(bv, ea)
    refs = list(_code_refs_to(bv, ea)) + list(_data_refs_to(bv, ea))
    refs.sort(key=lambda x: x[0])
    rows = []
    for src, kind, fname in refs:
        rows.append(f"  0x{src:x}  [{kind:12s}]  in {fname}")
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    title = f"Cross-references to 0x{ea:x}" + (f" ({target_name})" if target_name else "")
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=title,
        next_hint=f"Call xrefs_to with offset={next_offset} limit={page_limit}.",
    )


@tool(category="xrefs")
def xrefs_from(
    address: Annotated[str, "Source address (hex string)"],
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max results"] = 30,
) -> str:
    """Get cross-references from the given address with pagination."""
    bv = require_bv()
    ea = parse_addr_like(address)

    refs = _refs_from(bv, ea)
    rows = []
    for dst, kind in refs:
        target_name = resolve_name_at(bv, dst) or ""
        rows.append(f"  0x{dst:x}  [{kind:12s}]  {target_name}")
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=f"Cross-references from 0x{ea:x}",
        next_hint=f"Call xrefs_from with offset={next_offset} limit={page_limit}.",
    )


@tool(category="xrefs")
def function_xrefs(
    address: Annotated[str, "Function address (hex string)"],
) -> str:
    """Get cross-references to and from a function (callers + callees)."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    start = int(getattr(func, "start", ea))
    fname = get_function_name(func)

    callers = set()
    for c in list(getattr(func, "callers", []) or []):
        callers.add(get_function_name(c))
    if not callers:
        for src, _kind, _f in _code_refs_to(bv, start):
            cf = get_function_at(bv, src)
            if cf is not None and int(getattr(cf, "start", 0)) != start:
                callers.add(get_function_name(cf))

    callees = set()
    for c in list(getattr(func, "callees", []) or []):
        callees.add(get_function_name(c))

    return format_callers_callees(fname, start, callers, callees)
