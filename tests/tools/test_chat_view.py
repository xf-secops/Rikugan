"""Tests for rikugan.ui.chat_view — pure logic helpers."""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

from tests.qt_stubs import ensure_pyside6_stubs

ensure_pyside6_stubs()

# Stub all heavy submodules that chat_view imports.
# Reinstall them unconditionally because other tests may have left behind
# incomplete stubs in sys.modules.
for _mod_name in [
    "rikugan.agent.turn",
    "rikugan.core.types",
]:
    _stub = types.ModuleType(_mod_name)
    # Add commonly-needed attrs
    for _attr in [
        "PlanView", "TurnEvent",
        "TurnEventType", "Message", "Role", "TokenUsage", "ToolResult",
    ]:
        setattr(_stub, _attr, MagicMock())
    sys.modules[_mod_name] = _stub

_state_stub = types.ModuleType("rikugan.state.session")
_state_stub.INTERNAL_EVENT_CANCELLED = "cancelled"
_state_stub.INTERNAL_EVENT_KEY = "rikugan_internal"
sys.modules["rikugan.state.session"] = _state_stub

# Other tests may leave stubbed UI modules behind; force fresh imports.
for _mod_name in [
    "rikugan.ui.chat_view",
    "rikugan.ui.message_widgets",
    "rikugan.ui.plan_view",
    "rikugan.ui.tool_widgets",
]:
    sys.modules.pop(_mod_name, None)

from rikugan.ui.bulk_renamer import BulkRenamerWidget  # noqa: E402
from rikugan.ui.chat_view import _TOOL_GROUP_MIN_CALLS, _is_hidden_system_user_message  # noqa: E402

# ---------------------------------------------------------------------------
# _is_hidden_system_user_message
# ---------------------------------------------------------------------------

class TestIsHiddenSystemUserMessage(unittest.TestCase):
    def test_empty_string_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message(""))

    def test_none_equivalent_empty_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message(""))

    def test_system_prefix_returns_true(self):
        self.assertTrue(_is_hidden_system_user_message("[SYSTEM] some hint"))

    def test_system_prefix_with_leading_whitespace(self):
        self.assertTrue(_is_hidden_system_user_message("   [SYSTEM] some hint"))

    def test_regular_message_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message("Hello world"))

    def test_lowercase_system_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message("[system] hint"))

    def test_partial_system_keyword_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message("SYSTEM"))

    def test_system_in_middle_returns_false(self):
        self.assertFalse(_is_hidden_system_user_message("not [SYSTEM] hint"))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestChatViewConstants(unittest.TestCase):
    def test_tool_group_min_calls_is_positive(self):
        self.assertGreater(_TOOL_GROUP_MIN_CALLS, 0)

    def test_tool_group_min_calls_value(self):
        self.assertEqual(_TOOL_GROUP_MIN_CALLS, 2)


class TestBulkRenamerLookup(unittest.TestCase):
    def test_find_row_prefers_cached_mapping(self):
        widget = object.__new__(BulkRenamerWidget)
        widget._addr_to_row = {0x401000: 7}
        widget._table = MagicMock()
        self.assertEqual(widget._find_row_for_address(0x401000), 7)
        widget._table.rowCount.assert_not_called()


if __name__ == "__main__":
    unittest.main()
