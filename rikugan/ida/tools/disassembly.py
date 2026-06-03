"""Disassembly reading tools."""

from __future__ import annotations

import importlib
from typing import Annotated

from ...tools.base import parse_addr, tool
from ...tools.pagination import format_page, normalize_page

ida_funcs = idautils = idc = None  # populated below when IDA is available
try:
    ida_funcs = importlib.import_module("ida_funcs")
    idautils = importlib.import_module("idautils")
    idc = importlib.import_module("idc")
except ImportError:
    ida_funcs = idautils = idc = None  # IDA not present — tools unavailable in non-IDA context


@tool(category="disassembly")
def read_disassembly(
    address: Annotated[str, "Start address (hex string)"],
    offset: Annotated[int, "Instruction offset from the start address"] = 0,
    limit: Annotated[int, "Max instructions to return"] = 30,
    count: Annotated[int, "Deprecated: use limit instead"] = 0,
) -> str:
    """Read paginated disassembly starting at the given address."""

    ea = parse_addr(address)
    offset, limit = normalize_page(offset, count or limit)
    lines = []
    current_index = 0
    while len(lines) < limit:
        mnem = idc.print_insn_mnem(ea)
        if not mnem:
            break
        ops = idc.print_operand(ea, 0)
        op2 = idc.print_operand(ea, 1)
        if op2:
            ops += f", {op2}"
        op3 = idc.print_operand(ea, 2)
        if op3:
            ops += f", {op3}"

        comment = idc.get_cmt(ea, 0) or ""
        rep_comment = idc.get_cmt(ea, 1) or ""
        cmt = ""
        if comment:
            cmt = f"  ; {comment}"
        elif rep_comment:
            cmt = f"  ; {rep_comment}"

        if current_index >= offset:
            lines.append(f"  0x{ea:08x}  {mnem:8s} {ops}{cmt}")
        current_index += 1
        ea = idc.next_head(ea, ea + 0x1000)
        if ea == idc.BADADDR:
            break
    header = f"Disassembly from 0x{parse_addr(address):x} instructions {offset}-{offset + len(lines)}:"
    if ea != idc.BADADDR:
        lines.append(f"  ... continue with offset={offset + len(lines)} limit={limit}.")
    return "\n".join([header, *(lines or ["  (none)"])])


@tool(category="disassembly")
def read_function_disassembly(
    address: Annotated[str, "Function address (hex string)"],
    offset: Annotated[int, "Start instruction index for pagination"] = 0,
    limit: Annotated[int, "Max instructions to return"] = 120,
) -> str:
    """Read paginated disassembly of a function."""

    ea = parse_addr(address)
    func = ida_funcs.get_func(ea)
    if func is None:
        return f"No function at 0x{ea:x}"

    rows = []
    for head in idautils.FuncItems(func.start_ea):
        mnem = idc.print_insn_mnem(head)
        if not mnem:
            continue
        ops = idc.print_operand(head, 0)
        op2 = idc.print_operand(head, 1)
        if op2:
            ops += f", {op2}"
        op3 = idc.print_operand(head, 2)
        if op3:
            ops += f", {op3}"

        comment = idc.get_cmt(head, 0) or idc.get_cmt(head, 1) or ""
        cmt = f"  ; {comment}" if comment else ""
        rows.append(f"  0x{head:08x}  {mnem:8s} {ops}{cmt}")

    page_offset, page_limit = normalize_page(offset, limit)
    next_offset = min(len(rows), page_offset + page_limit)
    return format_page(
        rows,
        offset=offset,
        limit=limit,
        title=f"Disassembly for function 0x{func.start_ea:x}",
        next_hint=f"Call read_function_disassembly with offset={next_offset} limit={page_limit}.",
    )


@tool(category="disassembly")
def get_instruction_info(
    address: Annotated[str, "Instruction address (hex string)"],
) -> str:
    """Get detailed info about a single instruction."""

    ea = parse_addr(address)
    mnem = idc.print_insn_mnem(ea)
    if not mnem:
        return f"No instruction at 0x{ea:x}"

    size = idc.get_item_size(ea)
    ops = []
    for i in range(6):
        op = idc.print_operand(ea, i)
        if op:
            ops.append(op)

    # Get bytes
    byte_str = " ".join(f"{idc.get_wide_byte(ea + i):02x}" for i in range(size))

    parts = [
        f"Address: 0x{ea:x}",
        f"Mnemonic: {mnem}",
        f"Operands: {', '.join(ops) if ops else '(none)'}",
        f"Size: {size} bytes",
        f"Bytes: {byte_str}",
    ]

    comment = idc.get_cmt(ea, 0)
    if comment:
        parts.append(f"Comment: {comment}")

    return "\n".join(parts)
