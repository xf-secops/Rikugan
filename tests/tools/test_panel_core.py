"""Tests for rikugan.ui.panel_core — pure logic helpers."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

from tests.qt_stubs import ensure_pyside6_stubs
ensure_pyside6_stubs()

# Stub heavy rikugan submodules
for _mod_name in [
    "rikugan.ui.styles",
    "rikugan.ui.chat_view",
    "rikugan.ui.input_area",
    "rikugan.ui.context_bar",
    "rikugan.ui.tool_widgets",
    "rikugan.core.config",
    "rikugan.core.logging",
    "rikugan.core.types",
    "rikugan.agent.turn",
    "rikugan.agent.mutation",
    "rikugan.providers.auth_cache",
    "rikugan.providers.anthropic_provider",
    "rikugan.providers.ollama_provider",
    "rikugan.providers.registry",
]:
    if _mod_name not in sys.modules:
        _stub = types.ModuleType(_mod_name)
        for _attr in [
            "DARK_THEME", "ChatView", "InputArea", "ContextBar",
            "_SharedSpinnerTimer", "RikuganConfig",
            "log_error", "log_info", "log_debug",
            "TurnEvent", "TurnEventType", "MutationRecord",
            "Role", "ModelInfo",
            "resolve_auth_cached", "resolve_anthropic_auth",
            "DEFAULT_OLLAMA_URL", "ProviderRegistry",
        ]:
            setattr(_stub, _attr, MagicMock())
        sys.modules[_mod_name] = _stub

# Ensure DEFAULT_OLLAMA_URL is a string (used in comparisons)
_ollama_stub = sys.modules.get("rikugan.providers.ollama_provider")
if _ollama_stub and not isinstance(getattr(_ollama_stub, "DEFAULT_OLLAMA_URL", None), str):
    _ollama_stub.DEFAULT_OLLAMA_URL = "http://localhost:11434"

# Force-remove any stub that test_binja_panel/test_ida_panel may have registered
# so we always import the real module here.
sys.modules.pop("rikugan.ui.panel_core", None)

from rikugan.ui.panel_core import (  # noqa: E402
    _export_detect_lang, _export_format_tool_args,
    _export_format_tool_result, RikuganPanelCore,
    _TOOL_RESULT_TRUNCATE_CHARS,
)


# ---------------------------------------------------------------------------
# _export_detect_lang
# ---------------------------------------------------------------------------

class TestExportDetectLang(unittest.TestCase):
    def test_arg_key_code_returns_python(self):
        self.assertEqual(_export_detect_lang("anything", arg_key="code"), "python")

    def test_arg_key_python_returns_python(self):
        self.assertEqual(_export_detect_lang("anything", arg_key="python"), "python")

    def test_arg_key_c_code_returns_c(self):
        self.assertEqual(_export_detect_lang("anything", arg_key="c_code"), "c")

    def test_arg_key_c_declaration_returns_c(self):
        self.assertEqual(_export_detect_lang("anything", arg_key="c_declaration"), "c")

    def test_arg_key_prototype_returns_c(self):
        self.assertEqual(_export_detect_lang("anything", arg_key="prototype"), "c")

    def test_tool_name_execute_python(self):
        self.assertEqual(_export_detect_lang("x", tool_name="execute_python"), "python")

    def test_tool_name_decompile_function(self):
        self.assertEqual(_export_detect_lang("x", tool_name="decompile_function"), "c")

    def test_tool_name_get_il(self):
        self.assertEqual(_export_detect_lang("x", tool_name="get_il"), "c")

    def test_tool_name_fetch_disassembly(self):
        self.assertEqual(_export_detect_lang("x", tool_name="fetch_disassembly"), "x86asm")

    def test_hexdump_pattern_returns_text(self):
        hexdump = "00000000  48 65 6c 6c 6f 20 57 6f  72 6c 64 0a\n"
        self.assertEqual(_export_detect_lang(hexdump), "text")

    def test_asm_pattern_returns_x86asm(self):
        asm = "mov eax, 0x1234\ncall 0xdeadbeef\n"
        self.assertEqual(_export_detect_lang(asm), "x86asm")

    def test_c_pattern_returns_c(self):
        c_code = "int foo(void) {\n  if (x > 0) { return 1; }\n}"
        self.assertEqual(_export_detect_lang(c_code), "c")

    def test_python_pattern_returns_python(self):
        py_code = "def foo():\n    return 1\nimport os\n"
        self.assertEqual(_export_detect_lang(py_code), "python")

    def test_empty_returns_empty(self):
        self.assertEqual(_export_detect_lang(""), "")

    def test_plain_text_returns_empty(self):
        self.assertEqual(_export_detect_lang("hello world, nothing special"), "")

    def test_arg_key_takes_priority_over_tool_name(self):
        # arg_key check comes first
        result = _export_detect_lang("x", tool_name="execute_python", arg_key="c_code")
        self.assertEqual(result, "c")


# ---------------------------------------------------------------------------
# _export_format_tool_args
# ---------------------------------------------------------------------------

class TestExportFormatToolArgs(unittest.TestCase):
    def _make_tc(self, name: str, args: dict):
        tc = MagicMock()
        tc.name = name
        tc.arguments = args
        return tc

    def test_short_value_inline(self):
        tc = self._make_tc("tool", {"key": "val"})
        result = _export_format_tool_args(tc)
        self.assertIn("`key`", result)
        self.assertIn("'val'", result)

    def test_long_value_code_block(self):
        long_val = "x" * 100
        tc = self._make_tc("tool", {"code": long_val})
        result = _export_format_tool_args(tc)
        self.assertIn("```python", result)
        self.assertIn(long_val, result)

    def test_multiline_value_code_block(self):
        tc = self._make_tc("tool", {"body": "line1\nline2"})
        result = _export_format_tool_args(tc)
        self.assertIn("```", result)
        self.assertIn("line1\nline2", result)

    def test_empty_args(self):
        tc = self._make_tc("tool", {})
        result = _export_format_tool_args(tc)
        self.assertEqual(result, "")

    def test_multiple_args(self):
        tc = self._make_tc("tool", {"a": "short", "b": "also short"})
        result = _export_format_tool_args(tc)
        self.assertIn("`a`", result)
        self.assertIn("`b`", result)


# ---------------------------------------------------------------------------
# _export_format_tool_result
# ---------------------------------------------------------------------------

class TestExportFormatToolResult(unittest.TestCase):
    def _make_tr(self, content: str, name: str = "tool"):
        tr = MagicMock()
        tr.content = content
        tr.name = name
        return tr

    def test_short_content_not_truncated(self):
        tr = self._make_tr("short content")
        result = _export_format_tool_result(tr)
        self.assertIn("short content", result)
        self.assertNotIn("truncated", result)

    def test_long_content_truncated(self):
        long_content = "A" * (_TOOL_RESULT_TRUNCATE_CHARS + 100)
        tr = self._make_tr(long_content)
        result = _export_format_tool_result(tr)
        self.assertIn("truncated", result)
        self.assertNotIn("A" * (_TOOL_RESULT_TRUNCATE_CHARS + 1), result)

    def test_returns_code_block(self):
        tr = self._make_tr("output")
        result = _export_format_tool_result(tr)
        self.assertIn("```", result)
        self.assertTrue(result.startswith("```"))

    def test_decompile_tool_gets_c_hint(self):
        tr = self._make_tr("int main(void) {}", "decompile_function")
        result = _export_format_tool_result(tr)
        self.assertIn("```c", result)


# ---------------------------------------------------------------------------
# Panel logic via object.__new__ injection
# ---------------------------------------------------------------------------

def _make_panel():
    panel = object.__new__(RikuganPanelCore)
    panel._is_shutdown = False
    panel._polling = False
    panel._pending_answer = False
    panel._chat_views = {}
    panel._pending_restore_messages = {}
    panel._context_bar = None
    panel._mutation_panel = None
    panel._skills_refresh_timer = None
    panel._poll_timer = None
    panel._input_area = MagicMock()
    panel._send_btn = MagicMock()
    panel._cancel_btn = MagicMock()
    panel._mutations_btn = MagicMock()
    panel._count_label = MagicMock()
    panel._tab_widget = MagicMock()
    panel._tab_bar = MagicMock()
    panel._ctrl = MagicMock()
    panel._config = MagicMock()
    panel._ui_hooks = None
    panel._awaiting_button_approval = False
    return panel


class TestTabIdAtIndex(unittest.TestCase):
    def test_returns_none_when_widget_is_none(self):
        panel = _make_panel()
        panel._tab_widget.widget.return_value = None
        result = panel._tab_id_at_index(0)
        self.assertIsNone(result)

    def test_returns_tab_id_from_property(self):
        panel = _make_panel()
        mock_widget = MagicMock()
        mock_widget.property.return_value = "tab123"
        panel._chat_views["tab123"] = mock_widget
        panel._tab_widget.widget.return_value = mock_widget
        result = panel._tab_id_at_index(0)
        self.assertEqual(result, "tab123")

    def test_returns_none_when_property_not_in_chat_views(self):
        panel = _make_panel()
        mock_widget = MagicMock()
        mock_widget.property.return_value = "ghost_id"
        # ghost_id not in _chat_views, and widget itself is not in values either
        panel._tab_widget.widget.return_value = mock_widget
        result = panel._tab_id_at_index(0)
        self.assertIsNone(result)

    def test_fallback_to_widget_identity(self):
        panel = _make_panel()
        mock_widget = MagicMock()
        mock_widget.property.return_value = None  # no property
        panel._chat_views["tab_x"] = mock_widget
        panel._tab_widget.widget.return_value = mock_widget
        result = panel._tab_id_at_index(0)
        self.assertEqual(result, "tab_x")


class TestActiveChatView(unittest.TestCase):
    def test_returns_view_for_active_tab(self):
        panel = _make_panel()
        mock_view = MagicMock()
        panel._ctrl.active_tab_id = "t1"
        panel._chat_views["t1"] = mock_view
        self.assertIs(panel._active_chat_view(), mock_view)

    def test_returns_none_when_active_tab_not_in_views(self):
        panel = _make_panel()
        panel._ctrl.active_tab_id = "missing"
        self.assertIsNone(panel._active_chat_view())


class TestSetRunning(unittest.TestCase):
    def test_running_true_sets_queue_text(self):
        panel = _make_panel()
        panel._set_running(True)
        panel._send_btn.setText.assert_called_with("Queue")

    def test_running_false_sets_send_text(self):
        panel = _make_panel()
        panel._set_running(False)
        panel._send_btn.setText.assert_called_with("Send")

    def test_running_shows_cancel_btn(self):
        panel = _make_panel()
        panel._set_running(True)
        panel._cancel_btn.setVisible.assert_called_with(True)

    def test_not_running_hides_cancel_btn(self):
        panel = _make_panel()
        panel._set_running(False)
        panel._cancel_btn.setVisible.assert_called_with(False)


class TestUpdateTabBarVisibility(unittest.TestCase):
    def test_single_tab_hides_bar(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 1
        panel._update_tab_bar_visibility()
        panel._tab_bar.setVisible.assert_called_with(False)

    def test_two_tabs_shows_bar(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 2
        panel._update_tab_bar_visibility()
        panel._tab_bar.setVisible.assert_called_with(True)

    def test_zero_tabs_hides_bar(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 0
        panel._update_tab_bar_visibility()
        panel._tab_bar.setVisible.assert_called_with(False)


class TestOnCloseTab(unittest.TestCase):
    def test_does_not_close_last_tab(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 1
        panel._on_close_tab(0)
        panel._ctrl.close_tab.assert_not_called()

    def test_closes_tab_with_multiple(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 2
        mock_widget = MagicMock()
        mock_widget.property.return_value = "tid"
        panel._chat_views["tid"] = mock_widget
        panel._tab_widget.widget.return_value = mock_widget
        panel._on_close_tab(0)
        panel._ctrl.close_tab.assert_called_once_with("tid")

    def test_removes_view_from_chat_views(self):
        panel = _make_panel()
        panel._tab_widget.count.return_value = 2
        mock_widget = MagicMock()
        mock_widget.property.return_value = "tid"
        panel._chat_views["tid"] = mock_widget
        panel._tab_widget.widget.return_value = mock_widget
        panel._on_close_tab(0)
        self.assertNotIn("tid", panel._chat_views)


class TestOnToggleMutationLog(unittest.TestCase):
    def test_noop_when_no_panel(self):
        panel = _make_panel()
        panel._mutation_panel = None
        panel._on_toggle_mutation_log()  # must not raise

    def test_shows_when_hidden(self):
        panel = _make_panel()
        mock_mp = MagicMock()
        mock_mp.isVisible.return_value = False
        panel._mutation_panel = mock_mp
        panel._on_toggle_mutation_log()
        mock_mp.setVisible.assert_called_with(True)

    def test_hides_when_visible(self):
        panel = _make_panel()
        mock_mp = MagicMock()
        mock_mp.isVisible.return_value = True
        panel._mutation_panel = mock_mp
        panel._on_toggle_mutation_log()
        mock_mp.setVisible.assert_called_with(False)

    def test_updates_checked_state(self):
        panel = _make_panel()
        mock_mp = MagicMock()
        mock_mp.isVisible.return_value = False
        panel._mutation_panel = mock_mp
        panel._on_toggle_mutation_log()
        panel._mutations_btn.setChecked.assert_called_with(True)


class TestOnUndoRequested(unittest.TestCase):
    def test_noop_when_shutdown(self):
        panel = _make_panel()
        panel._is_shutdown = True
        panel._on_undo_requested(1)
        # _start_agent should not be called — we can check ctrl is not used
        panel._ctrl.start_agent.assert_not_called()

    def test_starts_undo_agent(self):
        panel = _make_panel()
        panel._ctrl.active_tab_id = "t1"
        mock_view = MagicMock()
        panel._chat_views["t1"] = mock_view
        panel._ctrl.start_agent.return_value = None  # no error
        # Pre-inject a mock poll_timer so _ensure_poll_timer returns early
        panel._poll_timer = MagicMock()
        panel._on_undo_requested(2)
        panel._ctrl.start_agent.assert_called_once_with("/undo 2")


class TestShutdownIdempotency(unittest.TestCase):
    def test_double_shutdown_safe(self):
        panel = _make_panel()
        panel._poll_timer = None
        panel._skills_refresh_timer = None
        panel._context_bar = None
        panel._ui_hooks = None
        panel.shutdown()
        panel.shutdown()  # second call must not raise or double-cleanup
        panel._ctrl.shutdown.assert_called_once()

    def test_shutdown_calls_ctrl_shutdown(self):
        panel = _make_panel()
        panel._poll_timer = None
        panel._skills_refresh_timer = None
        panel._context_bar = None
        panel._ui_hooks = None
        panel.shutdown()
        panel._ctrl.shutdown.assert_called_once()


class TestStopSkillsRefreshTimer(unittest.TestCase):
    def test_noop_when_timer_none(self):
        panel = _make_panel()
        panel._skills_refresh_timer = None
        panel._stop_skills_refresh_timer()  # must not raise

    def test_clears_timer_ref(self):
        panel = _make_panel()
        mock_timer = MagicMock()
        panel._skills_refresh_timer = mock_timer
        panel._stop_skills_refresh_timer()
        self.assertIsNone(panel._skills_refresh_timer)
        mock_timer.stop.assert_called_once()
        mock_timer.deleteLater.assert_called_once()


class TestRestoreMessagesIfNeeded(unittest.TestCase):
    def test_noop_when_no_pending_restore(self):
        panel = _make_panel()
        mock_view = MagicMock()
        panel._chat_views["t1"] = mock_view
        panel._restore_messages_if_needed("t1")
        mock_view.restore_from_messages.assert_not_called()

    def test_restores_pending_messages_once(self):
        panel = _make_panel()
        mock_view = MagicMock()
        panel._chat_views["t1"] = mock_view
        panel._pending_restore_messages["t1"] = ["m1", "m2"]
        panel._restore_messages_if_needed("t1")
        mock_view.restore_from_messages.assert_called_once_with(["m1", "m2"])
        self.assertNotIn("t1", panel._pending_restore_messages)


class TestUpdateTokenDisplay(unittest.TestCase):
    def test_noop_when_context_bar_none(self):
        panel = _make_panel()
        panel._context_bar = None
        panel._update_token_display(1000)  # must not raise

    def test_calls_set_tokens_with_given_count(self):
        panel = _make_panel()
        mock_cb = MagicMock()
        panel._context_bar = mock_cb
        panel._config.provider.context_window = 200000
        panel._update_token_display(5000)
        mock_cb.set_tokens.assert_called_once_with(5000, 200000)

    def test_zero_context_window_fallback(self):
        panel = _make_panel()
        mock_cb = MagicMock()
        panel._context_bar = mock_cb
        panel._config.provider.context_window = 0
        panel._update_token_display(1234)
        mock_cb.set_tokens.assert_called_once_with(1234, 0)


if __name__ == "__main__":
    unittest.main()
