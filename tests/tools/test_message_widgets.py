"""Tests for rikugan.ui.message_widgets — pure logic helpers."""

# ruff: noqa: E402, I001

from __future__ import annotations

import unittest

from tests.qt_stubs import ensure_pyside6_stubs

ensure_pyside6_stubs()

from rikugan.ui.message_widgets import _assistant_bubble_theme, _split_thinking


_LIGHT_TOKENS = {
    "panel": "#f2f2f2",
    "chat_canvas": "#eeeeee",
    "assistant_bg": "#e9e9e9",
    "tool_bg": "#ebebeb",
    "thinking_bg": "#e6e6e6",
    "input_bg": "#e4e4e4",
    "text": "#202020",
    "muted": "#8a8a8a",
    "subtle": "#626262",
    "border": "#b0b0b0",
    "accent": "#1476a8",
    "accent_text": "#ffffff",
    "code_bg": "#e2e2e2",
}

_DARK_TOKENS = {
    "panel": "#242424",
    "chat_canvas": "#2d2d2d",
    "assistant_bg": "#353535",
    "tool_bg": "#333333",
    "thinking_bg": "#393939",
    "input_bg": "#3c3c3c",
    "text": "#e6e6e6",
    "muted": "#888888",
    "subtle": "#aaaaaa",
    "border": "#555555",
    "accent": "#1678aa",
    "accent_text": "#ffffff",
    "code_bg": "#3a3a3a",
}


def _luminance(color: str) -> float:
    color = color.lstrip("#")
    r = int(color[0:2], 16) / 255.0
    g = int(color[2:4], 16) / 255.0
    b = int(color[4:6], 16) / 255.0
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


# ---------------------------------------------------------------------------
# _split_thinking
# ---------------------------------------------------------------------------

class TestSplitThinking(unittest.TestCase):
    def test_no_think_tags_returns_all_visible(self):
        thinking, visible = _split_thinking("Hello world")
        self.assertEqual(thinking, "")
        self.assertEqual(visible, "Hello world")

    def test_complete_think_block_extracted(self):
        thinking, visible = _split_thinking("Before <think>reasoning</think> After")
        self.assertEqual(thinking, "reasoning")
        self.assertEqual(visible, "Before  After".strip())

    def test_visible_part_stripped(self):
        _thinking, visible = _split_thinking("<think>A</think>   result   ")
        self.assertEqual(visible, "result")

    def test_multiple_think_blocks(self):
        text = "<think>step1</think> middle <think>step2</think> end"
        thinking, visible = _split_thinking(text)
        self.assertIn("step1", thinking)
        self.assertIn("step2", thinking)
        self.assertIn("end", visible)

    def test_empty_string(self):
        thinking, visible = _split_thinking("")
        self.assertEqual(thinking, "")
        self.assertEqual(visible, "")

    def test_unclosed_think_tag_partial_streaming(self):
        text = "Before <think>partial reasoning"
        thinking, visible = _split_thinking(text)
        self.assertIn("partial reasoning", thinking)
        self.assertEqual(visible, "Before")

    def test_empty_think_block(self):
        thinking, visible = _split_thinking("<think></think> result")
        self.assertEqual(thinking, "")
        self.assertEqual(visible, "result")

    def test_think_whitespace_stripped(self):
        thinking, _visible = _split_thinking("<think>  trimmed  </think> x")
        self.assertEqual(thinking, "trimmed")

    def test_multiline_think_block(self):
        text = "<think>\nline1\nline2\n</think> visible"
        thinking, visible = _split_thinking(text)
        self.assertIn("line1", thinking)
        self.assertIn("line2", thinking)
        self.assertEqual(visible, "visible")

    def test_no_visible_content_after_think(self):
        thinking, visible = _split_thinking("<think>inner</think>")
        self.assertEqual(thinking, "inner")
        self.assertEqual(visible, "")

    def test_unclosed_think_empty_partial(self):
        text = "Before <think>"
        thinking, visible = _split_thinking(text)
        self.assertEqual(thinking, "")  # empty partial not added
        self.assertEqual(visible, "Before")


class TestMessageBubbleThemes(unittest.TestCase):
    def test_light_assistant_bubble_uses_light_surface_with_dark_text(self):
        theme = _assistant_bubble_theme(_LIGHT_TOKENS)
        self.assertGreater(_luminance(theme["background"]), 0.75)
        self.assertLess(_luminance(theme["text"]), 0.25)

    def test_dark_assistant_bubble_uses_dark_surface_with_light_text(self):
        theme = _assistant_bubble_theme(_DARK_TOKENS)
        self.assertGreater(_luminance(theme["background"]), 0.15)
        self.assertLess(_luminance(theme["background"]), 0.35)
        self.assertGreater(_luminance(theme["text"]), 0.75)


if __name__ == "__main__":
    unittest.main()
