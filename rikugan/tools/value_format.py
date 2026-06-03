"""Readable formatting for data/global value tools."""

from __future__ import annotations

from collections.abc import Callable

_TYPE_SIZES = {
    "u8": 1,
    "i8": 1,
    "byte": 1,
    "u16": 2,
    "i16": 2,
    "word": 2,
    "u32": 4,
    "i32": 4,
    "dword": 4,
    "float": 4,
    "u64": 8,
    "i64": 8,
    "qword": 8,
    "double": 8,
    "ptr": 0,
    "pointer": 0,
}


def normalize_type_hint(type_hint: str | None) -> str:
    hint = (type_hint or "auto").strip().lower()
    return hint.replace("uint", "u").replace("int", "i")


def bytes_needed_for_type(type_hint: str, pointer_size: int, requested_size: int = 0) -> int:
    """Return how many bytes should be read to interpret *type_hint*."""
    hint = normalize_type_hint(type_hint)
    if hint in ("string", "str", "utf8", "utf-8", "utf16", "utf-16", "bytes", "auto"):
        return max(1, min(int(requested_size) if requested_size else 64, 256))
    size = _TYPE_SIZES.get(hint)
    if size is None:
        return max(1, min(int(requested_size) if requested_size else pointer_size, 256))
    if size == 0:
        return max(1, pointer_size)
    return size


def _hex_bytes(data: bytes) -> str:
    return " ".join(f"{b:02x}" for b in data)


def _printable_ascii(data: bytes) -> str:
    return "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in data)


def _trim_c_string(data: bytes) -> bytes:
    nul = data.find(b"\x00")
    return data if nul < 0 else data[:nul]


def _decode_utf8(data: bytes) -> str | None:
    raw = _trim_c_string(data)
    if not raw:
        return None
    try:
        text = raw.decode("utf-8", errors="replace")
    except UnicodeError:
        return None
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return text if printable >= max(1, int(len(text) * 0.8)) else None


def _decode_utf16(data: bytes) -> str | None:
    if len(data) < 2:
        return None
    raw = data
    for idx in range(0, max(0, len(data) - 1), 2):
        if data[idx : idx + 2] == b"\x00\x00":
            raw = data[:idx]
            break
    if not raw:
        return None
    try:
        text = raw.decode("utf-16-le", errors="replace")
    except UnicodeError:
        return None
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\r\n\t")
    return text if printable >= max(1, int(len(text) * 0.8)) else None


def _signed(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return value - (1 << bits) if value & sign else value


def format_global_value(
    *,
    address: int,
    data: bytes,
    pointer_size: int,
    type_hint: str = "auto",
    name: str = "",
    resolve_pointer: Callable[[int], str] | None = None,
) -> str:
    """Format raw bytes as a readable global/data value summary."""
    hint = normalize_type_hint(type_hint)
    label = f" ({name})" if name else ""
    lines = [f"Global value at 0x{address:x}{label}"]
    lines.append(f"Type hint: {hint}")
    lines.append(f"Bytes: {_hex_bytes(data)}")

    if hint in ("bytes",):
        lines.append(f"ASCII: {_printable_ascii(data)}")
        return "\n".join(lines)

    if hint in ("string", "str", "utf8", "utf-8", "auto"):
        text = _decode_utf8(data)
        if text is not None:
            lines.append(f"UTF-8 string: {text!r}")

    if hint in ("utf16", "utf-16", "auto"):
        text16 = _decode_utf16(data)
        if text16 is not None:
            lines.append(f"UTF-16LE string: {text16!r}")

    widths = [1, 2, 4, 8] if hint == "auto" else []
    explicit_width = _TYPE_SIZES.get(hint)
    if explicit_width:
        widths = [explicit_width]
    elif hint in ("ptr", "pointer"):
        widths = [pointer_size]

    seen: set[int] = set()
    for width in widths:
        if width in seen or width <= 0 or len(data) < width:
            continue
        seen.add(width)
        value = int.from_bytes(data[:width], "little", signed=False)
        bits = width * 8
        if hint.startswith("i") or hint == "auto":
            lines.append(f"{'i' if hint.startswith('i') else 's'}{bits}: {_signed(value, bits)}")
        if hint.startswith("u") or hint in ("byte", "word", "dword", "qword", "auto"):
            lines.append(f"u{bits}: {value} (0x{value:x})")

    if len(data) >= pointer_size and pointer_size in (4, 8):
        ptr = int.from_bytes(data[:pointer_size], "little", signed=False)
        target = resolve_pointer(ptr) if resolve_pointer else ""
        suffix = f" -> {target}" if target else ""
        lines.append(f"ptr{pointer_size * 8}: 0x{ptr:x}{suffix}")

    if len(lines) <= 3:
        lines.append(f"ASCII: {_printable_ascii(data)}")
    return "\n".join(lines)
