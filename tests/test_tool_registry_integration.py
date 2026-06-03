"""Integration tests for the tool registry with all built-in tools.

Tests that the default registry loads correctly, all tools have valid
schemas, and tools execute through the registry dispatch path.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

# Reload tool modules so they pick up real stub base classes (optinsn_t,
# Hexrays_Hooks, etc.) instead of MagicMock, which would leak fake
# _tool_definition attributes into the registry.
import importlib
import rikugan.ida.tools.microcode as _mc_mod
import rikugan.ida.tools.microcode_optim as _mco_mod
import rikugan.ida.tools.database as _db_mod
importlib.reload(_mco_mod)
importlib.reload(_mc_mod)
importlib.reload(_db_mod)

from rikugan.ida.tools.registry import create_default_registry
from rikugan.tools.registry import ToolRegistry


class TestDefaultRegistryCreation(unittest.TestCase):
    """Test that all built-in tool modules register successfully."""

    def setUp(self):
        self.registry = create_default_registry()

    def test_has_tools(self):
        tools = self.registry.list_names()
        self.assertTrue(len(tools) > 0)

    def test_minimum_tool_count(self):
        """Registry should have at least 20 tools across all modules."""
        tools = self.registry.list_names()
        self.assertGreaterEqual(len(tools), 20)

    def test_all_tools_have_descriptions(self):
        for defn in self.registry.list_tools():
            self.assertTrue(
                defn.description,
                f"Tool {defn.name} missing description",
            )

    def test_all_tools_have_handlers(self):
        for defn in self.registry.list_tools():
            self.assertIsNotNone(
                defn.handler,
                f"Tool {defn.name} missing handler",
            )

    def test_all_tools_have_valid_schemas(self):
        """Every tool must produce a valid JSON Schema dict."""
        for defn in self.registry.list_tools():
            schema = defn.to_json_schema()
            self.assertEqual(schema["type"], "object", f"{defn.name} schema type")
            self.assertIn("properties", schema, f"{defn.name} missing properties")

    def test_provider_format_all_tools(self):
        """Every tool must produce valid provider format for the LLM."""
        formats = self.registry.to_provider_format()
        self.assertEqual(len(formats), len(self.registry.list_tools()))
        for fmt in formats:
            self.assertEqual(fmt["type"], "function")
            self.assertIn("name", fmt["function"])
            self.assertIn("description", fmt["function"])
            self.assertIn("parameters", fmt["function"])


class TestRegistryCategories(unittest.TestCase):
    """Test that expected tool categories are present."""

    def setUp(self):
        self.registry = create_default_registry()

    def test_navigation_tools(self):
        names = self.registry.list_names()
        self.assertIn("get_cursor_position", names)
        self.assertIn("get_current_function", names)

    def test_function_tools(self):
        names = self.registry.list_names()
        self.assertIn("list_functions", names)
        self.assertIn("search_functions", names)
        self.assertIn("get_function_info", names)

    def test_database_tools(self):
        names = self.registry.list_names()
        self.assertIn("get_binary_info", names)
        self.assertIn("list_segments", names)
        self.assertIn("read_global_value", names)

    def test_decompiler_tool_surface_is_simplified(self):
        names = self.registry.list_names()
        self.assertIn("decompile_function", names)
        self.assertNotIn("get_pseudocode", names)

    def test_string_tools(self):
        names = self.registry.list_names()
        self.assertIn("list_strings", names)
        self.assertIn("search_strings", names)

    def test_annotation_tools(self):
        names = self.registry.list_names()
        self.assertIn("rename_function", names)
        self.assertIn("set_comment", names)

    def test_xref_tools(self):
        names = self.registry.list_names()
        self.assertIn("xrefs_to", names)
        self.assertIn("xrefs_from", names)


class TestRegistryExecution(unittest.TestCase):
    """Test tool execution through the registry dispatch path."""

    def setUp(self):
        self.registry = create_default_registry()

    def test_execute_list_functions(self):
        result = self.registry.execute("list_functions", {"offset": 0, "limit": 10})
        self.assertIn("Functions", result)

    def test_execute_get_binary_info(self):
        result = self.registry.execute("get_binary_info", {})
        self.assertIn("test_binary", result)

    def test_execute_search_functions(self):
        result = self.registry.execute("search_functions", {"query": "sub"})
        self.assertIn("sub_1000", result)

    def test_execute_unknown_tool_raises(self):
        from rikugan.core.errors import ToolNotFoundError
        with self.assertRaises(ToolNotFoundError):
            self.registry.execute("nonexistent_tool_xyz", {})

    def test_execute_wrong_args_raises(self):
        from rikugan.core.errors import ToolError
        with self.assertRaises(ToolError):
            # list_functions expects int for offset — @tool wraps TypeError as ToolError
            self.registry.execute("list_functions", {"offset": "not_an_int"})


class TestRegistryResultFormatting(unittest.TestCase):
    """Test result formatting and truncation."""

    def test_none_becomes_ok(self):
        self.assertEqual(ToolRegistry._format_result(None), "OK")

    def test_string_passthrough(self):
        self.assertEqual(ToolRegistry._format_result("hello"), "hello")

    def test_dict_becomes_json(self):
        result = ToolRegistry._format_result({"key": "val"})
        self.assertIn('"key"', result)
        self.assertIn('"val"', result)

    def test_list_becomes_json(self):
        result = ToolRegistry._format_result([1, 2, 3])
        self.assertIn("1", result)

    def test_other_types_become_str(self):
        result = ToolRegistry._format_result(42)
        self.assertEqual(result, "42")


if __name__ == "__main__":
    unittest.main()
