"""Message display widgets for the chat view."""

from __future__ import annotations

import random
import re as _re
from typing import ClassVar

from .markdown import md_to_html, resolve_markdown_theme
from .qt_compat import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    Qt,
    QTimer,
    QToolButton,
    QVBoxLayout,
    QWidget,
    qt_flags,
)
from .styles import blend_theme_color, get_chat_color_tokens, host_stylesheet

_THINKING_PHRASES = [
    "analyzing binary structure...",
    "examining control flow...",
    "tracing cross-references...",
    "inspecting disassembly...",
    "reading function signatures...",
    "correlating data references...",
    "mapping call graph...",
    "evaluating type patterns...",
    "scanning string references...",
    "deobfuscating logic...",
    "checking import table...",
    "inferring variable types...",
    "analyzing stack layout...",
    "tracing data flow...",
    "examining vtable references...",
    "decoding encoded values...",
]


_USER_ROLE = "#4ec9b0"
_ASSISTANT_ROLE = "#569cd6"
_BODY_TEXT = "#d4d4d4"
_MUTED_TEXT = "#808080"
_SUBTLE_TEXT = "#b0b0b0"
_USER_BUBBLE_BG = "#0e639c"
_USER_BUBBLE_BORDER = "#1177bb"
_ASSISTANT_BUBBLE_BG = "#151515"
_ASSISTANT_BUBBLE_BORDER = "#2c2c2c"
_THINKING_SURFACE_BG = "#1e1e1e"
_THINKING_BLOCK_BG = "#1a1a2e"
_THINKING_BLOCK_BORDER = "#2a2a3e"
_TOOL_BG = "#252526"
_TOOL_BORDER = "#3c3c3c"


def _color_luminance(color: str) -> float:
    color = color.lstrip("#")
    if len(color) != 6:
        return 0.0
    r = int(color[0:2], 16) / 255.0
    g = int(color[2:4], 16) / 255.0
    b = int(color[4:6], 16) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ensure_readable(fg: str, bg: str) -> str:
    """Return *fg* if it contrasts with *bg*, else a high-contrast fallback.

    Some host themes resolve a body-text color that sits too close to a darker
    control surface (e.g. the exploration-finding card), making small text hard
    to read.  This guarantees a legible color without disturbing themes whose
    foreground already has enough contrast.
    """
    if abs(_color_luminance(fg) - _color_luminance(bg)) >= 0.4:
        return fg
    return "#ececec" if _color_luminance(bg) < 0.5 else "#1a1a1a"


def _theme_colors(source=None) -> dict[str, str]:
    if isinstance(source, dict):
        return source
    return get_chat_color_tokens(source)


def _is_dark_theme(source=None) -> bool:
    return _color_luminance(_theme_colors(source)["panel"]) < 0.5


def _body_text(source=None) -> str:
    return _theme_colors(source)["text"]


def _muted_text(source=None) -> str:
    return _theme_colors(source)["muted"]


def _subtle_text(source=None) -> str:
    return _theme_colors(source)["subtle"]


def _border_color(source=None) -> str:
    return _theme_colors(source)["border"]


def _assistant_bubble_theme(source=None) -> dict[str, str]:
    colors = _theme_colors(source)
    return {
        "background": colors["assistant_bg"],
        "text": colors["text"],
        # Soft warm edge for a smoother bubble; fall back to the neutral border
        # if a caller passed a pre-built token dict without the new key.
        "border": colors.get("assistant_border", colors["border"]),
    }


def _user_bubble_theme(source=None) -> dict[str, str]:
    colors = _theme_colors(source)
    bg = colors["accent"] or _USER_BUBBLE_BG
    text = colors["accent_text"] or "#ffffff"
    if abs(_color_luminance(bg) - _color_luminance(text)) < 0.35:
        text = "#ffffff" if _color_luminance(bg) < 0.55 else "#1f1f1f"
    border = blend_theme_color(bg, colors["panel"], 0.2)
    return {"background": bg, "text": text, "border": border}


def _tool_surface(source=None) -> str:
    return _theme_colors(source)["tool_bg"]


def _thinking_surface(source=None) -> str:
    return _theme_colors(source)["thinking_bg"]


def _frame_css(*, background: str, border: str | None = None, radius: int = 8) -> str:
    border_css = f"border: 1px solid {border}; " if border else "border: none; "
    return f"background-color: {background}; {border_css}border-radius: {radius}px;"


def _bubble_css(
    *,
    background: str,
    text_color: str,
    border: str | None = None,
    radius: int = 10,
    padding: str = "8px 12px",
    size: int = 13,
) -> str:
    border_css = f"border: 1px solid {border}; " if border else "border: none; "
    return (
        f"background-color: {background}; color: {text_color}; "
        f"{border_css}border-radius: {radius}px; "
        f"padding: {padding}; font-size: {size}px;"
    )


def _native_text_style(
    *,
    size: int | None = None,
    bold: bool = False,
    italic: bool = False,
    monospace: bool = False,
) -> str:
    parts: list[str] = []
    if size is not None:
        parts.append(f"font-size: {size}px;")
    if bold:
        parts.append("font-weight: bold;")
    if italic:
        parts.append("font-style: italic;")
    if monospace:
        parts.append('font-family: Consolas, "Courier New", monospace;')
    return " ".join(parts)


def _tool_frame_style(
    source=None,
    accent: str | None = None,
    background: str | None = None,
    object_name: str = "message_tool",
) -> str:
    border = accent or _border_color(source)
    bg = background or _tool_surface(source)
    return f"QFrame#{object_name} {{ {_frame_css(background=bg, border=border, radius=6)} }}"


# Re-export tool widgets so existing consumers that import from this module
# continue to work without changes.


# ---------------------------------------------------------------------------
# Height-caching QLabel — eliminates O(text_length) layout-pass cost
# ---------------------------------------------------------------------------


class _HeightCachedLabel(QLabel):
    """QLabel that opts out of the layout heightForWidth protocol.

    QLabel with wordWrap forces an O(text_length) heightForWidth() call on
    every layout pass (e.g. when any sibling widget changes size).  In a chat
    with many long assistant messages this makes tool expand/collapse and
    parallel-tool completion O(N x msg_length) instead of O(N).

    By returning False from hasHeightForWidth() and pinning the height after
    each render, layout passes cost O(1) for this widget.  The correct height
    is still computed — just once per render instead of on every layout event.
    """

    def hasHeightForWidth(self) -> bool:
        return False

    def pin_height(self) -> None:
        """Fix widget height to the value heightForWidth returns for the current width."""
        w = self.width()
        if w <= 0:
            return
        h = QLabel.heightForWidth(self, w)
        if h > 0:
            self.setFixedHeight(h)

    def resizeEvent(self, event) -> None:
        # Re-pin whenever our own width settles to a new value. Without this, a
        # height pinned at an earlier (narrower) layout width stays too tall, and
        # QLabel's default vertical centering then leaves an empty band above and
        # below the text. Height-only changes don't re-trigger this (no width
        # change), so there's no layout loop.
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.pin_height()


# ---------------------------------------------------------------------------
# Collapsible section (unchanged, used internally)
# ---------------------------------------------------------------------------


class CollapsibleSection(QFrame):
    """A widget with a clickable header that shows/hides content."""

    def __init__(self, title: str, parent: QWidget = None):
        super().__init__(parent)
        self._expanded = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        # Header
        header = QHBoxLayout()
        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapse_button")
        self._toggle_btn.setText("▶")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.clicked.connect(self.toggle)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("tool_header")
        header.addWidget(self._toggle_btn)
        header.addWidget(self._title_label, 1)
        layout.addLayout(header)

        # Content area
        self._content = QWidget()
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(20, 0, 0, 0)
        self._content.setVisible(False)
        layout.addWidget(self._content)

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._content.setVisible(expanded)
        self._toggle_btn.setText("▼" if expanded else "▶")

    def content_layout(self) -> QVBoxLayout:
        return self._content_layout


# ---------------------------------------------------------------------------
# User message
# ---------------------------------------------------------------------------


class UserMessageWidget(QFrame):
    """Displays a user message."""

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_user")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self._role_label = QLabel("You")
        self._role_label.setStyleSheet(
            host_stylesheet(
                f"color: {_USER_ROLE}; font-weight: bold; font-size: 11px;",
                f"color: {_USER_ROLE}; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._role_label)

        bubble = _user_bubble_theme(parent or self)
        self._content = QLabel(text)
        self._content.setWordWrap(True)
        self._content.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
            )
        )
        self._content.setStyleSheet(
            _bubble_css(
                background=bubble["background"],
                text_color=bubble["text"],
                border=bubble["border"],
            )
        )
        self._content.setMinimumWidth(0)
        self._content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._content)


# ---------------------------------------------------------------------------
# Thinking content parser
# ---------------------------------------------------------------------------

_THINK_RE = _re.compile(r"<think>(.*?)</think>", _re.DOTALL)


def _split_thinking(text: str):
    """Split text into (thinking_content, visible_content).

    Handles:
    - One or more complete ``<think>...</think>`` blocks
    - An unclosed ``<think>`` during streaming
    """
    thinking_parts: list = []

    # Extract all complete <think>...</think> blocks
    last_end = 0
    visible_parts: list = []
    for m in _THINK_RE.finditer(text):
        visible_parts.append(text[last_end : m.start()])
        thinking_parts.append(m.group(1).strip())
        last_end = m.end()
    visible_parts.append(text[last_end:])
    remaining = "".join(visible_parts)

    # Check for unclosed <think> (still streaming)
    open_idx = remaining.rfind("<think>")
    if open_idx >= 0:
        partial = remaining[open_idx + 7 :].strip()
        if partial:
            thinking_parts.append(partial)
        remaining = remaining[:open_idx]

    return "\n\n".join(thinking_parts), remaining.strip()


# ---------------------------------------------------------------------------
# Collapsible thinking block
# ---------------------------------------------------------------------------


class _ThinkingBlock(QFrame):
    """Collapsible block for model reasoning / chain-of-thought."""

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("thinking_block")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                background=_thinking_surface(parent or self),
                object_name="thinking_block",
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)

        self._toggle = QToolButton()
        self._toggle.setObjectName("collapse_button")
        self._toggle.setText("\u25b6")  # ▶
        self._toggle.setFixedSize(14, 14)
        self._toggle.clicked.connect(self._on_toggle)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        header.addWidget(self._toggle)
        self._header_label = QLabel("Thinking")
        self._header_label.setStyleSheet(
            host_stylesheet(
                f"color: {_muted_text(parent or self)}; font-size: 11px; font-style: italic;",
                f"color: {_muted_text(parent or self)}; {_native_text_style(size=11, italic=True)}",
            )
        )
        header.addWidget(self._header_label, 1)
        layout.addLayout(header)

        self._content = QLabel()
        self._content.setWordWrap(True)
        self._content.setTextFormat(Qt.TextFormat.RichText)
        self._content.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
            )
        )
        self._content.setStyleSheet(
            host_stylesheet(
                f"color: {_subtle_text(parent or self)}; font-size: 12px;",
                f"color: {_subtle_text(parent or self)}; {_native_text_style(size=12, italic=True)}",
            )
        )
        self._content.hide()
        layout.addWidget(self._content)

        self._expanded = False
        self._md_theme: dict[str, str] | None = None
        self.hide()

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        self._toggle.setText("\u25bc" if self._expanded else "\u25b6")

    def set_thinking(self, text: str, in_progress: bool = False) -> None:
        if self._md_theme is None:
            self._md_theme = resolve_markdown_theme(self)
        self._content.setText(md_to_html(text, self, theme=self._md_theme))
        label = "Thinking\u2026" if in_progress else "Thinking"
        self._header_label.setText(label)
        self.show()


# ---------------------------------------------------------------------------
# Assistant message (with streaming + Markdown)
# ---------------------------------------------------------------------------


def _commit_index_in_tail(tail: str) -> int:
    """Return how many leading chars of *tail* form complete Markdown blocks.

    A safe commit point is a paragraph break (``\\n\\n``) that is not inside an
    open code fence.  ``tail`` is assumed to start at a block boundary with a
    *closed* fence state (guaranteed by the caller, which only commits whole
    blocks).  Uses ``str.find`` jumps so the scan is cheap even for code blocks.
    """
    in_fence = False
    pos = 0
    last = 0
    n = len(tail)
    while pos < n:
        fence = tail.find("```", pos)
        if not in_fence:
            limit = fence if fence != -1 else n
            nn = tail.find("\n\n", pos, limit)
            if nn != -1:
                pos = last = nn + 2
                continue
            if fence == -1:
                break
            in_fence = True
            pos = fence + 3
        else:
            if fence == -1:
                break  # unterminated fence — keep it in the live tail
            in_fence = False
            pos = fence + 3
    return last


class AssistantMessageWidget(QFrame):
    """Displays an assistant message with streaming support and Markdown rendering.

    Streaming is kept smooth on three fronts so per-frame cost stays O(tail)
    instead of O(message) — even for long answers:

    * **Display buffer (typewriter):** incoming deltas accumulate in
      ``_full_text`` while a ``_reveal_timer`` reveals them at a steady cadence,
      so bursty network arrival doesn't produce jumpy output.  The reveal rate
      catches up to the buffer so it never lags behind the model.
    * **Committed/tail split (two labels):** finalized Markdown blocks render
      once into ``_committed_label`` and are never re-parsed or re-laid-out;
      only the small in-progress *tail* is re-rendered into ``_tail_label`` each
      frame.  This bounds both the Markdown parse *and* the Qt rich-text layout
      to the tail.  On finalize everything collapses into the committed label so
      the message is a single selectable block.
    * **Thinking fast-path:** the ``<think>`` regex split only runs when a
      ``<think>`` tag is actually present (the common case skips it).
    """

    # Reveal cadence for the typewriter buffer (~33 fps).
    _REVEAL_INTERVAL_MS: int = 30
    # Reveal at least this many chars per tick so short tails still animate.
    _REVEAL_MIN_CHARS: int = 3
    # Drain a fraction of the backlog each tick so large bursts catch up fast
    # without snapping (remaining // divisor chars per tick).
    _REVEAL_CATCHUP_DIVISOR: int = 3

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_assistant")
        self._full_text = ""
        self._displayed_len = 0
        # Incrementally rendered HTML for finalized visible blocks (B2).
        self._committed_html = ""
        self._committed_visible_len = 0
        # Resolve the markdown theme once; reuse it on every streaming frame so
        # render cost excludes palette reads and color blends. The host theme is
        # effectively constant for a message's lifetime.
        self._md_theme: dict[str, str] | None = None
        # Optional callback fired after each render so the parent can follow the
        # typewriter reveal (which happens between delta arrivals).
        self._render_callback = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self._role_label = QLabel("Rikugan")
        self._role_label.setStyleSheet(
            host_stylesheet(
                f"color: {_ASSISTANT_ROLE}; font-weight: bold; font-size: 11px;",
                f"color: {_ASSISTANT_ROLE}; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._role_label)

        self._thinking_block = _ThinkingBlock()
        layout.addWidget(self._thinking_block)

        # The bubble is a frame carrying the surface (bg/border/radius); the
        # committed and tail labels live inside it with transparent backgrounds
        # so the two stacked labels read as one continuous bubble.
        bubble = _assistant_bubble_theme(parent or self)
        self._bubble = QFrame()
        self._bubble.setObjectName("message_assistant_bubble")
        self._bubble.setStyleSheet(
            f"QFrame#message_assistant_bubble {{ {_frame_css(background=bubble['background'], border=bubble['border'], radius=10)} }}"
        )
        bubble_layout = QVBoxLayout(self._bubble)
        bubble_layout.setContentsMargins(12, 8, 12, 8)  # emulates bubble padding
        bubble_layout.setSpacing(0)

        self._committed_label = self._make_content_label(bubble["text"])
        self._committed_label.hide()
        bubble_layout.addWidget(self._committed_label)
        self._tail_label = self._make_content_label(bubble["text"])
        bubble_layout.addWidget(self._tail_label)

        self._bubble.setMinimumWidth(0)
        self._bubble.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._bubble)

        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(self._REVEAL_INTERVAL_MS)
        self._reveal_timer.timeout.connect(self._reveal_tick)

    @staticmethod
    def _make_content_label(text_color: str) -> _HeightCachedLabel:
        label = _HeightCachedLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
                Qt.TextInteractionFlag.LinksAccessibleByMouse,
            )
        )
        label.setOpenExternalLinks(True)
        # Top-align so multi-line content never gets vertically centered (QLabel
        # defaults to AlignVCenter, which looks like a big gap above the text).
        label.setAlignment(qt_flags(Qt.AlignmentFlag.AlignLeft, Qt.AlignmentFlag.AlignTop))
        label.setStyleSheet(f"background: transparent; color: {text_color}; font-size: 13px;")
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        return label

    def set_render_callback(self, callback) -> None:
        """Register a callback fired after each render (e.g. scroll-to-bottom)."""
        self._render_callback = callback

    def _md_theme_cached(self) -> dict[str, str]:
        if self._md_theme is None:
            self._md_theme = resolve_markdown_theme(self)
        return self._md_theme

    def _update_thinking(self, text: str) -> str:
        """Sync the thinking block from *text*; return the visible portion.

        Fast-path: the ``<think>`` regex split only runs when a tag is present,
        so the common (no-reasoning) case avoids an O(n) scan per frame.
        """
        if "<think>" not in text:
            self._thinking_block.hide()
            return text
        thinking, visible = _split_thinking(text)
        if thinking:
            in_progress = "</think>" not in text
            self._thinking_block.set_thinking(thinking, in_progress=in_progress)
        else:
            self._thinking_block.hide()
        return visible

    def _render_progressive(self) -> None:
        """Render the revealed text, re-parsing/laying out only the tail."""
        theme = self._md_theme_cached()
        visible = self._update_thinking(self._full_text[: self._displayed_len])

        # Visible text is append-only in practice; reset defensively if it shrank
        # (e.g. a <think> block resolving) so the committed prefix stays valid.
        if self._committed_visible_len > len(visible):
            self._committed_html = ""
            self._committed_visible_len = 0
            self._committed_label.clear()
            self._committed_label.hide()

        tail = visible[self._committed_visible_len :]
        commit = _commit_index_in_tail(tail)
        if commit > 0:
            segment = tail[:commit]
            self._committed_html += md_to_html(segment, self, theme=theme) + "<br>"
            self._committed_visible_len += commit
            tail = visible[self._committed_visible_len :]
            # Committed label changes only when a block finalizes (infrequent),
            # so its layout cost is paid once per block, not per frame.
            self._committed_label.setText(self._committed_html)
            self._committed_label.show()
            self._committed_label.pin_height()

        self._tail_label.setText(md_to_html(tail, self, theme=theme))
        self._tail_label.setVisible(bool(tail))
        self._tail_label.pin_height()
        if self._render_callback is not None:
            self._render_callback()

    def _render_full(self) -> None:
        """Render the entire message into the committed label (finalize/restore)."""
        theme = self._md_theme_cached()
        visible = self._update_thinking(self._full_text)
        self._committed_label.setText(md_to_html(visible, self, theme=theme))
        self._committed_label.show()
        self._committed_label.pin_height()
        self._tail_label.clear()
        self._tail_label.hide()

    def _reveal_tick(self) -> None:
        remaining = len(self._full_text) - self._displayed_len
        if remaining <= 0:
            self._reveal_timer.stop()
            return
        step = max(self._REVEAL_MIN_CHARS, remaining // self._REVEAL_CATCHUP_DIVISOR)
        self._displayed_len = min(len(self._full_text), self._displayed_len + step)
        self._render_progressive()
        if self._displayed_len >= len(self._full_text):
            self._reveal_timer.stop()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._committed_label.pin_height()
            self._tail_label.pin_height()

    def append_text(self, delta: str) -> None:
        self._full_text += delta
        # Drive rendering from the reveal timer rather than the arrival cadence,
        # so a burst of deltas animates smoothly instead of jumping.
        if not self._reveal_timer.isActive():
            self._reveal_timer.start()

    def set_text(self, text: str) -> None:
        # Finalize/restore: snap to the authoritative full render so nothing is
        # left half-revealed and the committed/tail split can't drift.
        self._reveal_timer.stop()
        self._full_text = text
        self._displayed_len = len(text)
        self._committed_html = ""
        self._committed_visible_len = 0
        self._render_full()
        # During session restore, setUpdatesEnabled(False) is active when this
        # is called, so the widget has no width yet and pin_height() returns
        # early. Schedule a deferred call so it re-pins after the layout pass.
        if self._committed_label.width() <= 0:
            QTimer.singleShot(0, self._committed_label.pin_height)

    def full_text(self) -> str:
        return self._full_text


# ---------------------------------------------------------------------------
# Thinking indicator
# ---------------------------------------------------------------------------


class ThinkingWidget(QFrame):
    """Animated thinking indicator shown while the LLM is processing."""

    _STAR_FRAMES: ClassVar[list[str]] = ["✳", "✴", "✵", "✶"]

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_thinking")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                background=_thinking_surface(parent or self),
                object_name="message_thinking",
            )
        )
        self._phrase_idx = random.randint(0, len(_THINKING_PHRASES) - 1)
        self._star_idx = 0

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._star_label = QLabel(self._STAR_FRAMES[0])
        self._star_label.setStyleSheet(
            host_stylesheet(
                "color: #dcdcaa; font-size: 14px;",
                f"color: #dcdcaa; {_native_text_style(size=14)}",
            )
        )
        self._star_label.setFixedWidth(18)
        layout.addWidget(self._star_label)

        self._phrase_label = QLabel(_THINKING_PHRASES[self._phrase_idx])
        self._phrase_label.setStyleSheet(
            host_stylesheet(
                f"color: {_muted_text(parent or self)}; font-style: italic; font-size: 12px;",
                f"color: {_muted_text(parent or self)}; {_native_text_style(size=12, italic=True)}",
            )
        )
        layout.addWidget(self._phrase_label, 1)

        self._stopped = False

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(900)

    def _tick(self) -> None:
        if self._stopped:
            return
        self._star_idx = (self._star_idx + 1) % len(self._STAR_FRAMES)
        self._star_label.setText(self._STAR_FRAMES[self._star_idx])

        if self._star_idx == 0:
            self._phrase_idx = (self._phrase_idx + 1) % len(_THINKING_PHRASES)
            self._phrase_label.setText(_THINKING_PHRASES[self._phrase_idx])

    def stop(self) -> None:
        self._stopped = True
        try:
            self._timer.stop()
            self._timer.timeout.disconnect(self._tick)
        except (RuntimeError, TypeError):
            return  # timer already stopped or signal already disconnected — harmless


# ---------------------------------------------------------------------------
# Other message widgets
# ---------------------------------------------------------------------------


class QueuedMessageWidget(QFrame):
    """Displays a queued user message with dashed border."""

    def __init__(self, text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_queued")
        queued_bg = _thinking_surface(parent or self)
        queued_border = _theme_colors(parent or self)["accent"]
        self.setStyleSheet(
            f"QFrame#message_queued {{ border: 1px dashed {queued_border}; "
            f"border-radius: 6px; background: {queued_bg}; }}"
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        content_layout = QVBoxLayout()

        self._role_label = QLabel("You")
        self._role_label.setStyleSheet(
            host_stylesheet(
                f"color: {_USER_ROLE}; font-weight: bold; font-size: 11px;",
                f"color: {_USER_ROLE}; {_native_text_style(size=11, bold=True)}",
            )
        )
        content_layout.addWidget(self._role_label)

        self._content = QLabel(text)
        self._content.setWordWrap(True)
        self._content.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
            )
        )
        self._content.setStyleSheet(
            host_stylesheet(
                f"color: {_body_text(parent or self)}; font-size: 13px;",
                f"color: {_body_text(parent or self)}; {_native_text_style(size=13)}",
            )
        )
        content_layout.addWidget(self._content)

        layout.addLayout(content_layout, 1)

        self._badge = QLabel("[queued]")
        self._badge.setStyleSheet(
            host_stylesheet(
                f"color: {_muted_text(parent or self)}; font-size: 10px; font-style: italic;",
                f"color: {_muted_text(parent or self)}; {_native_text_style(size=10, italic=True)}",
            )
        )
        self._badge.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(self._badge)


class UserQuestionWidget(QFrame):
    """Displays a question from the agent to the user with clickable option buttons."""

    def __init__(self, question: str, options: list | None = None, parent: QWidget = None):
        super().__init__(parent)
        self._option_selected_callback = None
        self.setObjectName("message_question")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                accent="#dcdcaa",
                background=_thinking_surface(parent or self),
                object_name="message_question",
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        self._header = QLabel("Rikugan asks:")
        self._header.setStyleSheet(
            host_stylesheet(
                "color: #dcdcaa; font-weight: bold; font-size: 11px;",
                f"color: #dcdcaa; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._header)

        self._q_label = QLabel(question)
        self._q_label.setWordWrap(True)
        self._q_label.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
            )
        )
        self._q_label.setStyleSheet(
            host_stylesheet(
                f"color: {_body_text(parent or self)}; font-size: 13px;",
                f"color: {_body_text(parent or self)}; {_native_text_style(size=13)}",
            )
        )
        layout.addWidget(self._q_label)

        if options:
            btn_layout = QHBoxLayout()
            btn_layout.setContentsMargins(0, 4, 0, 0)
            btn_layout.setSpacing(8)
            for opt in options:
                btn = QPushButton(opt)
                button_css = (
                    "QPushButton { background: #2d4a6e; color: #9cdcfe; border: 1px solid #4a7ab5; "
                    "border-radius: 4px; padding: 4px 14px; font-size: 12px; }"
                    "QPushButton:hover { background: #3a5a8a; }"
                    "QPushButton:pressed { background: #1a3a5e; }"
                    "QPushButton:disabled { color: #808080; background: #1e2a3a; border-color: #444; }"
                )
                btn.setStyleSheet(host_stylesheet(button_css, button_css))
                btn.clicked.connect(lambda checked, o=opt: self._on_option(o))
                btn_layout.addWidget(btn)
            btn_layout.addStretch()
            layout.addLayout(btn_layout)
            self._buttons = btn_layout

    def set_option_selected_callback(self, callback) -> None:
        self._option_selected_callback = callback

    def _on_option(self, option: str) -> None:
        # Disable all buttons after selection
        for i in range(self._buttons.count()):
            item = self._buttons.itemAt(i)
            if item and item.widget():
                item.widget().setEnabled(False)
        if self._option_selected_callback is not None:
            self._option_selected_callback(option)


class ExplorationPhaseWidget(QFrame):
    """Displays an exploration phase transition."""

    _PHASE_ICONS: ClassVar[dict[str, str]] = {
        "explore": "\u25b6",  # play
        "plan": "\u270e",  # pencil
        "execute": "\u2699",  # gear
        "save": "\u2714",  # checkmark
    }

    def __init__(self, from_phase: str, to_phase: str, reason: str = "", parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                accent="#d7ba7d",
                background=_thinking_surface(parent or self),
            )
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        icon = self._PHASE_ICONS.get(to_phase, "\u2192")
        self._phase_label = QLabel(f"{icon}  Phase: {to_phase.upper()}")
        self._phase_label.setStyleSheet(
            host_stylesheet(
                "color: #d7ba7d; font-weight: bold; font-size: 11px;",
                f"color: #d7ba7d; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._phase_label)

        if reason:
            self._reason_label = QLabel(reason)
            self._reason_label.setWordWrap(True)
            self._reason_label.setStyleSheet(
                host_stylesheet(
                    "color: #b0a070; font-size: 11px;",
                    f"color: #b0a070; {_native_text_style(size=11)}",
                )
            )
            layout.addWidget(self._reason_label, 1)


class ExplorationFindingWidget(QFrame):
    """Displays a single exploration finding."""

    _CATEGORY_COLORS: ClassVar[dict[str, str]] = {
        "function_purpose": "#4ec9b0",
        "hypothesis": "#d7ba7d",
        "constant": "#b5cea8",
        "data_structure": "#c586c0",
        "string_ref": "#ce9178",
        "import_usage": "#569cd6",
        "patch_result": "#6a9955",
        "general": "#808080",
    }

    def __init__(
        self,
        category: str,
        summary: str,
        address: str | None = None,
        relevance: str = "medium",
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self.setObjectName("message_tool")
        src = parent or self
        color = self._CATEGORY_COLORS.get(category, "#808080")
        self.setStyleSheet(_tool_frame_style(source=src, accent=color))

        # Resolve text colors against the actual card surface so the summary
        # stays readable even when the host theme's body text is low-contrast.
        surface = _tool_surface(src)
        summary_color = _ensure_readable(_body_text(src), surface)
        addr_color = _ensure_readable(_muted_text(src), surface)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self._cat_label = QLabel(f"[{category}]")
        self._cat_label.setStyleSheet(
            host_stylesheet(
                f"color: {color}; font-weight: bold; font-size: 10px;",
                f"color: {color}; {_native_text_style(size=10, bold=True)}",
            )
        )
        layout.addWidget(self._cat_label)

        if address:
            self._addr_label = QLabel(address)
            self._addr_label.setStyleSheet(
                host_stylesheet(
                    f"color: {addr_color}; font-family: monospace; font-size: 11px;",
                    f"color: {addr_color}; {_native_text_style(size=11, monospace=True)}",
                )
            )
            layout.addWidget(self._addr_label)

        self._summary_label = QLabel(summary)
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet(
            host_stylesheet(
                f"color: {summary_color}; font-size: 12px;",
                f"color: {summary_color}; {_native_text_style(size=12)}",
            )
        )
        layout.addWidget(self._summary_label, 1)

        if relevance == "high":
            rel_label = QLabel("\u2605")
            rel_label.setStyleSheet(
                host_stylesheet(
                    "color: #d7ba7d; font-size: 12px;",
                    f"color: #d7ba7d; {_native_text_style(size=12, bold=True)}",
                )
            )
            rel_label.setToolTip("High relevance")
            layout.addWidget(rel_label)


class ResearchNoteWidget(QFrame):
    """Displays a research note saved event."""

    def __init__(
        self,
        title: str,
        genre: str,
        path: str,
        preview: str = "",
        review_passed: bool = True,
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self.setObjectName("message_tool")
        accent = "#6a9955" if review_passed else "#d7ba7d"
        self.setStyleSheet(_tool_frame_style(source=parent or self, accent=accent))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        # Header row
        header = QHBoxLayout()
        icon = "\u2705" if review_passed else "\u270f"  # checkmark or pencil
        self._title_label = QLabel(f"{icon}  {title}")
        self._title_label.setStyleSheet(
            host_stylesheet(
                f"color: {accent}; font-weight: bold; font-size: 11px;",
                f"color: {accent}; {_native_text_style(size=11, bold=True)}",
            )
        )
        header.addWidget(self._title_label)

        self._genre_label = QLabel(f"#{genre}")
        self._genre_label.setStyleSheet(
            host_stylesheet(
                f"color: {_muted_text(parent or self)}; font-size: 10px; font-style: italic;",
                f"color: {_muted_text(parent or self)}; {_native_text_style(size=10, italic=True)}",
            )
        )
        header.addWidget(self._genre_label)
        header.addStretch()
        layout.addLayout(header)

        # Path
        self._path_label = QLabel(path)
        self._path_label.setStyleSheet(
            host_stylesheet(
                f"color: {_muted_text(parent or self)}; font-family: monospace; font-size: 10px;",
                f"color: {_muted_text(parent or self)}; {_native_text_style(size=10, monospace=True)}",
            )
        )
        layout.addWidget(self._path_label)

        # Preview
        if preview:
            self._preview_label = QLabel(preview)
            self._preview_label.setWordWrap(True)
            self._preview_label.setStyleSheet(
                host_stylesheet(
                    f"color: {_body_text(parent or self)}; font-size: 11px;",
                    f"color: {_body_text(parent or self)}; {_native_text_style(size=11)}",
                )
            )
            layout.addWidget(self._preview_label)


class SubagentEventWidget(QFrame):
    """Displays a subagent lifecycle event (spawned, completed, failed)."""

    _STATUS_COLORS: ClassVar[dict[str, str]] = {
        "spawned": "#569cd6",
        "completed": "#4ec9b0",
        "failed": "#f44747",
    }

    def __init__(
        self,
        status: str,
        name: str,
        detail: str = "",
        parent: QWidget = None,
    ):
        super().__init__(parent)
        self.setObjectName("message_tool")
        color = self._STATUS_COLORS.get(status, "#808080")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                accent=color,
                background=_tool_surface(parent or self),
            )
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)

        icon_map = {"spawned": "\u25b6", "completed": "\u2714", "failed": "\u2718"}
        icon = icon_map.get(status, "\u2022")
        self._icon = QLabel(icon)
        self._icon.setStyleSheet(
            host_stylesheet(
                f"color: {color}; font-size: 14px;",
                f"color: {color}; {_native_text_style(size=14)}",
            )
        )
        layout.addWidget(self._icon)

        label_text = f"Subagent \u201c{name}\u201d {status}"
        self._label = QLabel(label_text)
        self._label.setStyleSheet(
            host_stylesheet(
                f"color: {color}; font-weight: bold; font-size: 11px;",
                f"color: {color}; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._label)

        if detail:
            self._detail = QLabel(detail)
            self._detail.setWordWrap(True)
            self._detail.setStyleSheet(
                host_stylesheet(
                    f"color: {_subtle_text(parent or self)}; font-size: 11px;",
                    f"color: {_subtle_text(parent or self)}; {_native_text_style(size=11)}",
                )
            )
            layout.addWidget(self._detail, 1)


class ErrorMessageWidget(QFrame):
    """Displays an error message."""

    def __init__(self, error_text: str, parent: QWidget = None):
        super().__init__(parent)
        self.setObjectName("message_tool")
        self.setStyleSheet(
            _tool_frame_style(
                source=parent or self,
                accent="#f44747",
            )
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        self._header = QLabel("Error")
        self._header.setStyleSheet(
            host_stylesheet(
                "color: #f44747; font-weight: bold; font-size: 11px;",
                f"color: #f44747; {_native_text_style(size=11, bold=True)}",
            )
        )
        layout.addWidget(self._header)

        self._content = QLabel(error_text)
        self._content.setWordWrap(True)
        self._content.setTextInteractionFlags(
            qt_flags(
                Qt.TextInteractionFlag.TextSelectableByMouse,
                Qt.TextInteractionFlag.TextSelectableByKeyboard,
            )
        )
        self._content.setStyleSheet(
            host_stylesheet(
                "color: #f44747; font-size: 12px;",
                f"color: #f44747; {_native_text_style(size=12)}",
            )
        )
        self._content.setMinimumWidth(0)
        self._content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._content)
