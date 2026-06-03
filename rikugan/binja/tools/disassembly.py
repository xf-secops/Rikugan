"""Disassembly reading tools for Binary Ninja."""

from __future__ import annotations

from typing import Annotated

from ...tools.base import tool
from ...tools.pagination import format_page, normalize_page
from .comment_utils import get_comment_at
from .compat import parse_addr_like, read_bytes_safe, require_bv
from .disasm_utils import (
    get_disassembly_line,
    get_instruction_len,
    get_instruction_text_tokens,
    render_tokens,
)
from .fn_utils import (
    get_function_at,
    get_function_name,
    iter_function_instruction_addresses,
)


def _format_line(bv, ea: int) -> str:
    text = get_disassembly_line(bv, ea)
    if not text:
        return ""
    comment = get_comment_at(bv, ea)
    cmt = f"  ; {comment}" if comment else ""
    return f"  0x{ea:08x}  {text}{cmt}"


@tool(category="disassembly")
def read_disassembly(
    address: Annotated[str, "Start address (hex string)"],
    offset: Annotated[int, "Instruction offset from the start address"] = 0,
    limit: Annotated[int, "Max instructions to return"] = 30,
    count: Annotated[int, "Deprecated: use limit instead"] = 0,
) -> str:
    """Read paginated disassembly starting at the given address."""
    bv = require_bv()
    ea = parse_addr_like(address)
    offset, limit = normalize_page(offset, count or limit)
    lines: list[str] = []
    current_index = 0
    while len(lines) < limit:
        line = _format_line(bv, ea)
        if not line:
            break
        if current_index >= offset:
            lines.append(line)
        current_index += 1
        step = get_instruction_len(bv, ea)
        if step <= 0:
            break
        ea += step
    header = f"Disassembly from 0x{parse_addr_like(address):x} instructions {offset}-{offset + len(lines)}:"
    if len(lines) >= limit:
        lines.append(f"  ... continue with offset={offset + len(lines)} limit={limit}.")
    return "\n".join([header, *(lines or ["  (none)"])])


@tool(category="disassembly")
def read_function_disassembly(
    address: Annotated[str, "Function address (hex string)"],
    offset: Annotated[int, "Start instruction index for pagination"] = 0,
    limit: Annotated[int, "Max instructions to return"] = 120,
) -> str:
    """Read paginated disassembly of a function."""
    bv = require_bv()
    ea = parse_addr_like(address)
    func = get_function_at(bv, ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    start = int(getattr(func, "start", ea))
    rows = []
    for insn_ea in iter_function_instruction_addresses(func):
        line = _format_line(bv, insn_ea)
        if line:
            rows.append(line)
    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=f"Disassembly for {get_function_name(func)} at 0x{start:x}",
        next_hint=f"Call read_function_disassembly with offset={next_offset} limit={page_limit}.",
    )


@tool(category="disassembly")
def get_instruction_info(
    address: Annotated[str, "Instruction address (hex string)"],
) -> str:
    """Get detailed info about a single instruction."""
    bv = require_bv()
    ea = parse_addr_like(address)

    toks, tok_len = get_instruction_text_tokens(bv, ea)
    text = render_tokens(toks) if toks else get_disassembly_line(bv, ea)
    if not text:
        return f"No instruction at 0x{ea:x}"

    size = tok_len if tok_len > 0 else get_instruction_len(bv, ea)
    if size <= 0:
        size = 1

    mnemonic = text.split(None, 1)[0] if text.strip() else "?"
    operands = text[len(mnemonic) :].strip() if len(text) > len(mnemonic) else ""

    data = read_bytes_safe(bv, ea, size)
    byte_str = " ".join(f"{b:02x}" for b in data[:size])

    parts = [
        f"Address: 0x{ea:x}",
        f"Mnemonic: {mnemonic}",
        f"Operands: {operands if operands else '(none)'}",
        f"Size: {size} bytes",
        f"Bytes: {byte_str}",
    ]
    comment = get_comment_at(bv, ea)
    if comment:
        parts.append(f"Comment: {comment}")
    return "\n".join(parts)
