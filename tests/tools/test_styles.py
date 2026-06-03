"""Tests for host-aware UI style helpers."""

from __future__ import annotations

import sys
import unittest

sys.modules.pop("rikugan.ui.styles", None)

from rikugan.ui.styles import (  # noqa: E402
    IDA_NATIVE_THEME,
    _hex_luminance,
    _normalize_ida_palette,
    build_chat_sidebar_stylesheet,
    build_chat_view_stylesheet,
    build_input_area_stylesheet,
    get_chat_color_tokens,
)

_DARK_COLORS = {
    "window": "#242424",
    "window_text": "#e6e6e6",
    "base": "#ffffff",
    "alt_base": "#ffffff",
    "text": "#e6e6e6",
    "button": "#303030",
    "button_text": "#e6e6e6",
    "highlight": "#1678aa",
    "highlight_text": "#ffffff",
    "mid": "#666666",
    "dark": "#181818",
    "light": "#4a4a4a",
}

_LIGHT_COLORS = {
    "window": "#f2f2f2",
    "window_text": "#202020",
    "base": "#ffffff",
    "alt_base": "#eeeeee",
    "text": "#202020",
    "button": "#eeeeee",
    "button_text": "#202020",
    "highlight": "#1476a8",
    "highlight_text": "#ffffff",
    "mid": "#9a9a9a",
    "dark": "#d0d0d0",
    "light": "#ffffff",
}


class TestNormalizeIdaPalette(unittest.TestCase):
    def test_dark_window_with_dark_text_uses_readable_text(self):
        colors = {
            "window": "#303030",
            "window_text": "#000000",
            "base": "#ffffff",
            "alt_base": "#ffffff",
            "text": "#000000",
            "button": "#ffffff",
            "button_text": "#000000",
            "highlight": "#007acc",
            "highlight_text": "#ffffff",
            "mid": "#808080",
            "dark": "#101010",
            "light": "#f3f3f3",
        }

        normalized = _normalize_ida_palette(colors)

        self.assertEqual(normalized["window_text"], "#d4d4d4")
        self.assertEqual(normalized["text"], "#d4d4d4")
        self.assertEqual(normalized["button_text"], "#d4d4d4")
        self.assertNotEqual(normalized["button"], "#ffffff")


class TestInputAreaStylesheet(unittest.TestCase):
    def test_dark_theme_input_surface_is_not_black(self):
        css = build_input_area_stylesheet(_DARK_COLORS)

        self.assertNotIn("background-color: #000000", css)
        self.assertNotIn("color: #000000", css)
        self.assertIn("color:", css)


class TestChatColorTokens(unittest.TestCase):
    def test_dark_window_with_white_base_still_uses_dark_chat_canvas(self):
        tokens = get_chat_color_tokens(_DARK_COLORS)

        self.assertLess(_hex_luminance(tokens["chat_canvas"]), 0.25)
        self.assertLess(_hex_luminance(tokens["assistant_bg"]), 0.35)
        self.assertGreater(_hex_luminance(tokens["text"]), 0.75)

    def test_light_window_uses_light_chat_canvas_with_dark_text(self):
        tokens = get_chat_color_tokens(_LIGHT_COLORS)

        self.assertGreater(_hex_luminance(tokens["chat_canvas"]), 0.80)
        self.assertLess(_hex_luminance(tokens["text"]), 0.25)

    def test_non_ida_chat_view_stylesheet_explicitly_styles_scroll_and_container(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: False
        try:
            css = build_chat_view_stylesheet(_DARK_COLORS)
            self.assertIn("QScrollArea#chat_scroll", css)
            self.assertIn("QWidget#chat_container", css)
            self.assertNotIn("background-color: #ffffff", css)
        finally:
            _s.use_native_host_theme = _orig

    def test_non_ida_chat_view_stylesheet_includes_viewport_selector(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: False
        try:
            css = build_chat_view_stylesheet(_DARK_COLORS)
            self.assertIn("QScrollArea#chat_scroll > QWidget {", css)
        finally:
            _s.use_native_host_theme = _orig

    def test_ida_chat_view_stylesheet_only_fixes_viewport(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: True
        try:
            css = build_chat_view_stylesheet(_DARK_COLORS)
            # Only the viewport rule — no explicit background on scroll area or container
            self.assertIn("QScrollArea#chat_scroll > QWidget", css)
            self.assertIn("background: transparent", css)
            self.assertNotIn("QWidget#chat_container", css)
        finally:
            _s.use_native_host_theme = _orig

    def test_ida_sidebar_stylesheet_is_empty(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: True
        try:
            css = build_chat_sidebar_stylesheet(_DARK_COLORS)
            self.assertEqual(css, "")
        finally:
            _s.use_native_host_theme = _orig

    def test_non_ida_sidebar_row_labels_have_transparent_background(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: False
        try:
            css = build_chat_sidebar_stylesheet(_DARK_COLORS)
            self.assertIn("chat_row_title", css)
            self.assertIn("background: transparent", css)
        finally:
            _s.use_native_host_theme = _orig

    def test_non_ida_sidebar_list_has_no_border(self):
        import rikugan.ui.styles as _s
        _orig = _s.use_native_host_theme
        _s.use_native_host_theme = lambda: False
        try:
            css = build_chat_sidebar_stylesheet(_DARK_COLORS)
            self.assertIn("border: none", css)
        finally:
            _s.use_native_host_theme = _orig


class TestIdaNativeTheme(unittest.TestCase):
    def test_makes_panel_transparent(self):
        self.assertIn("QWidget#rikugan_panel", IDA_NATIVE_THEME)
        self.assertIn("transparent", IDA_NATIVE_THEME)

    def test_chat_scroll_is_transparent(self):
        self.assertIn("QScrollArea#chat_scroll", IDA_NATIVE_THEME)
        self.assertIn("QWidget#chat_container", IDA_NATIVE_THEME)


if __name__ == "__main__":
    unittest.main()
