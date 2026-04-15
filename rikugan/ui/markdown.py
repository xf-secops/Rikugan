"""Lightweight Markdown to HTML converter for QLabel rich text.

Handles the subset of Markdown that LLMs commonly produce:
- Fenced code blocks (```lang ... ```)
- Inline code (`code`)
- Bold (**text**), italic (*text*)
- Headers (# through ####)
- Bullet lists (- item, * item)
- Numbered lists (1. item)
- Links [text](url)
- Paragraphs (double newline)
- Horizontal rules (---, ***)

No external dependencies. Output targets Qt's supported HTML subset.
"""

from __future__ import annotations

import html
import re

from .styles import blend_theme_color, get_host_palette_colors, use_native_host_theme

_MARKDOWN_HINT_RE = re.compile(
    r"(^#{1,4}\s)|(^\s*[-*]\s+)|(^\s*\d+[.)]\s+)|```|`[^`]+`|\*\*|__|(?<!\w)\*(.+?)\*(?!\w)|(?<!\w)_(.+?)_(?!\w)|\[[^\]]+\]\([^)]+\)|^[-*_]{3,}\s*$",
    re.MULTILINE,
)


def _theme_markdown_styles(source=None) -> dict[str, str]:
    if use_native_host_theme():
        return {
            "inline_code_style": "font-family:monospace;",
            "block_code_style": "font-family:monospace; white-space:pre-wrap;",
            "link_style": "text-decoration: underline;",
            "hr_style": "",
            "heading_style": "font-weight:bold;",
            "lang_tag_style": "font-size:10px;",
        }

    colors = get_host_palette_colors(source)
    code_bg = blend_theme_color(colors["base"], colors["window"], 0.15)
    inline_fg = blend_theme_color(colors["highlight"], colors["text"], 0.3)
    border = blend_theme_color(colors["mid"], colors["window"], 0.35)
    heading = blend_theme_color(colors["highlight"], colors["text"], 0.15)
    return {
        "inline_code_style": (
            f"background-color:{code_bg}; color:{inline_fg}; "
            "padding:1px 4px; border-radius:3px; font-family:monospace; font-size:12px;"
        ),
        "block_code_style": (
            f"background-color:{colors['base']}; color:{colors['text']}; "
            f"border:1px solid {border}; border-radius:4px; "
            "padding:8px; font-family:monospace; font-size:12px; "
            "white-space:pre-wrap; word-break:break-all;"
        ),
        "link_style": f"color:{colors['highlight']};",
        "hr_style": f"border:1px solid {border};",
        "heading_style": f"color:{heading}; font-weight:bold;",
        "lang_tag_style": f"color:{blend_theme_color(colors['text'], colors['window'], 0.45)};font-size:10px;",
    }


def _has_markdown_syntax(text: str) -> bool:
    """Return True when the input likely needs markdown processing."""
    return bool(text and _MARKDOWN_HINT_RE.search(text))


def md_to_html(text: str, source=None) -> str:
    """Convert a Markdown string to Qt-compatible HTML."""
    if not text:
        return ""
    theme = _theme_markdown_styles(source)
    if not _has_markdown_syntax(text):
        escaped = html.escape(text).replace("\n", "<br>")
        return re.sub(r"(<br>\s*){3,}", "<br><br>", escaped)

    # Phase 1: extract fenced code blocks to protect them from inline processing
    blocks: list[str] = []

    def _stash_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = html.escape(m.group(2).strip("\n"))
        lang_tag = f'<span style="{theme["lang_tag_style"]}">{html.escape(lang)}</span><br>' if lang else ""
        block_html = f'<div style="{theme["block_code_style"]}">{lang_tag}{code}</div>'
        blocks.append(block_html)
        return f"\x00BLOCK{len(blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", _stash_block, text, flags=re.DOTALL)

    # Phase 2: process line-by-line for block-level elements
    lines = text.split("\n")
    out_lines: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Block placeholder — pass through
        if re.match(r"^\x00BLOCK\d+\x00$", stripped):
            # Close any open paragraph before the block
            out_lines.append(stripped)
            i += 1
            continue

        # Horizontal rule
        if re.match(r"^[-*_]{3,}\s*$", stripped):
            hr_style = f' style="{theme["hr_style"]}"' if theme["hr_style"] else ""
            out_lines.append(f"<hr{hr_style}>")
            i += 1
            continue

        # Headers
        hm = re.match(r"^(#{1,4})\s+(.*)", stripped)
        if hm:
            level = len(hm.group(1))
            sizes = {1: 18, 2: 16, 3: 14, 4: 13}
            size = sizes.get(level, 13)
            h_text = _inline(hm.group(2), theme)
            out_lines.append(
                f'<div style="{theme["heading_style"]}font-size:{size}px;margin:6px 0 2px 0;">{h_text}</div>'
            )
            i += 1
            continue

        # Bullet list — collect consecutive items
        if re.match(r"^[-*]\s+", stripped):
            items: list[str] = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                item_text = re.sub(r"^\s*[-*]\s+", "", lines[i])
                items.append(f"<li>{_inline(item_text, theme)}</li>")
                i += 1
            out_lines.append("<ul style='margin:2px 0 2px 16px;'>" + "".join(items) + "</ul>")
            continue

        # Numbered list — collect consecutive items
        if re.match(r"^\d+[.)]\s+", stripped):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+[.)]\s+", lines[i]):
                item_text = re.sub(r"^\s*\d+[.)]\s+", "", lines[i])
                items.append(f"<li>{_inline(item_text, theme)}</li>")
                i += 1
            out_lines.append("<ol style='margin:2px 0 2px 16px;'>" + "".join(items) + "</ol>")
            continue

        # Empty line → paragraph break
        if not stripped:
            out_lines.append("<br>")
            i += 1
            continue

        # Regular text
        out_lines.append(_inline(stripped, theme))
        i += 1

    result = "<br>".join(out_lines)

    # Phase 3: restore code blocks
    for idx, block_html in enumerate(blocks):
        result = result.replace(f"\x00BLOCK{idx}\x00", block_html)

    # Clean up double <br> from paragraph joins
    result = re.sub(r"(<br>\s*){3,}", "<br><br>", result)

    return result


def _inline(text: str, theme: dict[str, str] | None = None) -> str:
    """Apply inline Markdown formatting to a line of text."""
    theme = theme or _theme_markdown_styles()
    text = html.escape(text)

    # Stash inline code spans so bold/italic don't mangle their contents
    code_spans: list[str] = []

    def _stash_code(m: re.Match) -> str:
        code_spans.append(f'<span style="{theme["inline_code_style"]}">{m.group(1)}</span>')
        return f"\x01CODE{len(code_spans) - 1}\x01"

    text = re.sub(r"`([^`]+)`", _stash_code, text)

    # Now apply bold/italic/links on the text with code safely stashed
    text = _inline_formatting(text, theme["link_style"])

    # Restore code spans
    for idx, span_html in enumerate(code_spans):
        text = text.replace(f"\x01CODE{idx}\x01", span_html)

    return text


def _inline_formatting(text: str, link_style: str | None = None) -> str:
    """Apply bold, italic, and link formatting."""
    link_style = link_style or _theme_markdown_styles()["link_style"]
    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ (but not inside words for underscore)
    text = re.sub(r"(?<!\w)\*(.+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_(.+?)_(?!\w)", r"<i>\1</i>", text)

    # Links: [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        rf'<a style="{link_style}" href="\2">\1</a>',
        text,
    )

    return text
