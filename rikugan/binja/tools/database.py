"""Database-level tools for Binary Ninja."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated

from ...tools.base import tool
from ...tools.pagination import format_page, normalize_page
from ...tools.value_format import bytes_needed_for_type, format_global_value
from .compat import parse_addr_like, read_bytes_safe, require_bv
from .fn_utils import iter_functions
from .sym_utils import (
    is_export_symbol,
    is_import_symbol,
    iter_symbols,
    iter_symbols_by_name,
    resolve_name_at,
    symbol_address,
    symbol_name,
)


def _segment_name_for_addr(bv, ea: int) -> str:
    sections = getattr(bv, "sections", None)
    if isinstance(sections, dict):
        for name, sec in sections.items():
            start = int(getattr(sec, "start", 0))
            end = int(getattr(sec, "end", start))
            if start <= ea < end:
                return str(name)
    return ""


def _iter_segments(bv) -> Iterable[tuple[str, int, int, str]]:
    segments = getattr(bv, "segments", None)
    if segments is None:
        return []

    rows = []
    for seg in list(segments):
        start = int(getattr(seg, "start", 0))
        end = int(getattr(seg, "end", start))
        perms = ""
        if bool(getattr(seg, "readable", False)):
            perms += "R"
        if bool(getattr(seg, "writable", False)):
            perms += "W"
        if bool(getattr(seg, "executable", False)):
            perms += "X"
        rows.append((_segment_name_for_addr(bv, start), start, end, perms))
    return rows


@tool(category="database")
def list_segments() -> str:
    """List all segments in the binary."""
    bv = require_bv()
    lines = ["Segments:"]
    for name, start, end, perms in _iter_segments(bv):
        size = max(0, end - start)
        disp = name or "<segment>"
        lines.append(f"  {disp:16s}  0x{start:x}\u20130x{end:x}  ({size:#x} bytes)  {perms}")
    return "\n".join(lines)


@tool(category="database")
def list_imports(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max imports to return"] = 80,
) -> str:
    """List imported functions with pagination."""
    bv = require_bv()
    imports = []
    for sym in iter_symbols(bv):
        if not is_import_symbol(sym):
            continue
        ea = symbol_address(sym)
        if ea is None:
            continue
        imports.append((ea, symbol_name(sym)))
    imports.sort(key=lambda x: x[0])

    rows = [f"  0x{ea:x}  {name}" for ea, name in imports]
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title="Imports",
        next_hint=f"Call list_imports with offset={next_offset} limit={page_limit}.",
    )


@tool(category="database")
def list_exports(
    offset: Annotated[int, "Start index for pagination"] = 0,
    limit: Annotated[int, "Max exports to return"] = 80,
) -> str:
    """List exported functions/symbols with pagination."""
    bv = require_bv()
    exports = []
    for sym in iter_symbols(bv):
        if not is_export_symbol(sym):
            continue
        ea = symbol_address(sym)
        if ea is None:
            continue
        exports.append((ea, symbol_name(sym)))
    exports.sort(key=lambda x: x[0])

    rows = [f"  0x{ea:x}  {name}" for ea, name in exports]
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title="Exports",
        next_hint=f"Call list_exports with offset={next_offset} limit={page_limit}.",
    )


@tool(category="database")
def get_binary_info() -> str:
    """Get general information about the loaded binary."""
    bv = require_bv()
    lines = []

    filename = None
    fobj = getattr(bv, "file", None)
    if fobj is not None:
        filename = (
            getattr(fobj, "filename", None)
            or getattr(fobj, "original_filename", None)
            or getattr(fobj, "raw_filename", None)
        )
    if not filename:
        filename = getattr(bv, "file_name", None) or "<unknown>"
    lines.append(f"File: {filename}")

    arch = getattr(getattr(bv, "arch", None), "name", None)
    if arch:
        lines.append(f"Processor: {arch}")

    address_size = getattr(getattr(bv, "arch", None), "address_size", None)
    if isinstance(address_size, int) and address_size > 0:
        lines.append(f"Bits: {address_size * 8}")

    entry = None
    for attr in ("entry_point", "start"):
        val = getattr(bv, attr, None)
        if isinstance(val, int):
            entry = val
            break
    if entry is not None:
        lines.append(f"Entry point: 0x{entry:x}")

    start = getattr(bv, "start", None)
    end = getattr(bv, "end", None)
    if isinstance(start, int):
        lines.append(f"Min address: 0x{start:x}")
    if isinstance(end, int):
        lines.append(f"Max address: 0x{end:x}")

    view_type = getattr(bv, "view_type", None) or getattr(bv, "name", None)
    if view_type:
        lines.append(f"File type: {view_type}")

    lines.append(f"Functions: {len(iter_functions(bv))}")
    return "\n".join(lines)


@tool(category="database")
def read_bytes(
    address: Annotated[str, "Start address (hex string)"],
    size: Annotated[int, "Number of bytes to read"] = 64,
) -> str:
    """Read raw bytes at an address and return as hex dump."""
    bv = require_bv()
    _MAX_READ_BYTES = 1024
    ea = parse_addr_like(address)
    size = int(size)
    if size > _MAX_READ_BYTES:
        size = _MAX_READ_BYTES
    if size < 0:
        size = 0

    data = read_bytes_safe(bv, ea, size)
    lines = []
    for off in range(0, size, 16):
        row_ea = ea + off
        chunk = data[off : off + 16]
        hex_parts = [f"{b:02x}" for b in chunk]
        while len(hex_parts) < 16:
            hex_parts.append("  ")
        ascii_str = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
        ascii_str = ascii_str.ljust(16)
        hex_str = " ".join(hex_parts[:8]) + "  " + " ".join(hex_parts[8:])
        lines.append(f"  0x{row_ea:08x}  {hex_str}  |{ascii_str}|")
    return "\n".join(lines)


def _resolve_addr_or_name(bv, value: str) -> int:
    try:
        return parse_addr_like(value)
    except (TypeError, ValueError):
        matches = iter_symbols_by_name(bv, value)
        for sym in matches:
            ea = symbol_address(sym)
            if ea is not None:
                return ea
        raise ValueError(f"Unknown address or name: {value}") from None


def _pointer_size(bv) -> int:
    size = getattr(getattr(bv, "arch", None), "address_size", None)
    if isinstance(size, int) and size > 0:
        return size
    return 8


@tool(category="database")
def read_global_value(
    address: Annotated[str, "Global/data address or symbol name"],
    type_hint: Annotated[
        str,
        "auto, u8/i8/u16/i16/u32/i32/u64/i64, ptr, string, utf16, or bytes",
    ] = "auto",
    size: Annotated[int, "Bytes to inspect for auto/string/bytes; 0 selects a sensible default"] = 0,
) -> str:
    """Read and interpret a global variable or data value."""
    bv = require_bv()
    ea = _resolve_addr_or_name(bv, address)
    pointer_size = _pointer_size(bv)
    read_size = bytes_needed_for_type(type_hint, pointer_size, requested_size=size)
    data = read_bytes_safe(bv, ea, read_size)
    return format_global_value(
        address=ea,
        data=data,
        pointer_size=pointer_size,
        type_hint=type_hint,
        name=resolve_name_at(bv, ea),
        resolve_pointer=lambda ptr: resolve_name_at(bv, ptr),
    )
