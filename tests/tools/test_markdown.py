"""Tests for rikugan.ui.markdown — Markdown-to-HTML converter."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from rikugan.ui.markdown import (
    _has_markdown_syntax,
    _inline,
    _inline_formatting,
    _theme_markdown_styles,
    md_to_html,
)

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


class TestMdToHtmlEmptyAndNone(unittest.TestCase):
    def test_empty_string_returns_empty(self):
        self.assertEqual(md_to_html(""), "")

    def test_plain_text_passthrough(self):
        result = md_to_html("hello world")
        self.assertIn("hello world", result)


class TestHasMarkdownSyntax(unittest.TestCase):
    def test_plain_text_returns_false(self):
        self.assertFalse(_has_markdown_syntax("hello world"))

    def test_newline_only_returns_false(self):
        self.assertFalse(_has_markdown_syntax("hello\nworld"))

    def test_bold_marker_returns_true(self):
        self.assertTrue(_has_markdown_syntax("**bold**"))

    def test_header_marker_returns_true(self):
        self.assertTrue(_has_markdown_syntax("# Title"))


class TestMdToHtmlHeaders(unittest.TestCase):
    def test_h1(self):
        result = md_to_html("# Title")
        self.assertIn("<div", result)
        self.assertIn("Title", result)
        self.assertIn("18px", result)

    def test_h2(self):
        result = md_to_html("## Heading")
        self.assertIn("16px", result)

    def test_h3(self):
        result = md_to_html("### Sub")
        self.assertIn("14px", result)

    def test_h4(self):
        result = md_to_html("#### Small")
        self.assertIn("13px", result)


class TestMdToHtmlHorizontalRule(unittest.TestCase):
    def test_triple_dash(self):
        result = md_to_html("---")
        self.assertIn("<hr", result)

    def test_triple_star(self):
        result = md_to_html("***")
        self.assertIn("<hr", result)

    def test_triple_underscore(self):
        result = md_to_html("___")
        self.assertIn("<hr", result)


class TestMdToHtmlBulletList(unittest.TestCase):
    def test_dash_list(self):
        result = md_to_html("- item one\n- item two")
        self.assertIn("<ul", result)
        self.assertIn("<li>", result)
        self.assertIn("item one", result)
        self.assertIn("item two", result)

    def test_star_list(self):
        result = md_to_html("* alpha\n* beta")
        self.assertIn("<ul", result)
        self.assertIn("alpha", result)


class TestMdToHtmlNumberedList(unittest.TestCase):
    def test_numbered_list_with_period(self):
        result = md_to_html("1. first\n2. second")
        self.assertIn("<ol", result)
        self.assertIn("first", result)
        self.assertIn("second", result)

    def test_numbered_list_with_paren(self):
        result = md_to_html("1) alpha\n2) beta")
        self.assertIn("<ol", result)
        self.assertIn("alpha", result)


class TestMdToHtmlFencedCodeBlock(unittest.TestCase):
    def test_code_block_rendered(self):
        result = md_to_html("```python\nx = 1\n```")
        self.assertIn("x = 1", result)
        self.assertIn("white-space:pre", result)

    def test_code_block_with_lang_tag(self):
        result = md_to_html("```python\ncode\n```")
        self.assertIn("python", result)

    def test_code_block_without_lang(self):
        result = md_to_html("```\nraw code\n```")
        self.assertIn("raw code", result)

    def test_code_block_escapes_html(self):
        result = md_to_html("```\n<script>alert(1)</script>\n```")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_code_block_not_processed_for_inline(self):
        result = md_to_html("```\n**not bold**\n```")
        self.assertNotIn("<b>not bold</b>", result)


class TestMdToHtmlParagraph(unittest.TestCase):
    def test_empty_line_becomes_br(self):
        result = md_to_html("para one\n\npara two")
        self.assertIn("<br>", result)

    def test_multiple_empty_lines_collapsed(self):
        result = md_to_html("a\n\n\n\nb")
        # Three or more consecutive <br> should be collapsed to two
        self.assertNotIn("<br><br><br>", result)


class TestInlineFormatting(unittest.TestCase):
    def test_bold_double_star(self):
        result = _inline_formatting("**bold**")
        self.assertEqual(result, "<b>bold</b>")

    def test_bold_double_underscore(self):
        result = _inline_formatting("__bold__")
        self.assertEqual(result, "<b>bold</b>")

    def test_italic_single_star(self):
        result = _inline_formatting("*italic*")
        self.assertEqual(result, "<i>italic</i>")

    def test_italic_single_underscore(self):
        result = _inline_formatting("_italic_")
        self.assertEqual(result, "<i>italic</i>")

    def test_link(self):
        result = _inline_formatting("[text](http://example.com)")
        self.assertIn('<a', result)
        self.assertIn("href", result)
        self.assertIn("text", result)
        self.assertIn("http://example.com", result)

    def test_no_spurious_formatting(self):
        result = _inline_formatting("plain text")
        self.assertEqual(result, "plain text")


class TestInlineCodeSpans(unittest.TestCase):
    def test_backtick_code_rendered(self):
        result = _inline("use `foo()` here")
        self.assertIn("<span", result)
        self.assertIn("foo()", result)
        self.assertIn("font-family:monospace", result)

    def test_bold_inside_code_not_applied(self):
        result = _inline("`**not bold**`")
        self.assertNotIn("<b>", result)
        self.assertIn("**not bold**", result)

    def test_html_escaped_in_text(self):
        result = _inline("<b>not bold</b>")
        self.assertNotIn("<b>", result)
        self.assertIn("&lt;b&gt;", result)


class TestMarkdownThemeStyles(unittest.TestCase):
    def test_light_theme_code_styles_use_dark_text_on_light_surface(self):
        with patch("rikugan.ui.markdown.get_chat_color_tokens", return_value=_LIGHT_TOKENS):
            styles = _theme_markdown_styles()
        self.assertIn("background-color:#e2e2e2", styles["block_code_style"])
        self.assertIn("color:#202020", styles["block_code_style"])
        self.assertIn("color:#1476a8", styles["link_style"])

    def test_dark_theme_code_styles_use_light_text_on_dark_surface(self):
        with patch("rikugan.ui.markdown.get_chat_color_tokens", return_value=_DARK_TOKENS):
            styles = _theme_markdown_styles()
        self.assertIn("background-color:#3a3a3a", styles["block_code_style"])
        self.assertIn("color:#e6e6e6", styles["block_code_style"])


class TestMdToHtmlIntegration(unittest.TestCase):
    def test_mixed_content(self):
        md = "# Title\n\nSome **bold** and `code`.\n\n- item\n- item2"
        result = md_to_html(md)
        self.assertIn("<b>bold</b>", result)
        self.assertIn("<ul", result)
        self.assertIn("Title", result)

    def test_nested_inline_in_header(self):
        result = md_to_html("# **Bold Title**")
        self.assertIn("<b>Bold Title</b>", result)

    def test_link_in_list(self):
        result = md_to_html("- [link](http://x.com)")
        self.assertIn("href", result)
        self.assertIn("<li>", result)


if __name__ == "__main__":
    unittest.main()
