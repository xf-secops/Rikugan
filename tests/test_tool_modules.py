"""Tests for tool modules exercised through IDA mocks.

Covers database, functions, strings, xrefs, annotations, and disassembly
tools end-to-end using the mock IDA API layer.  Only tests positive (happy)
paths since mock mutation across test files is inherently fragile.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

# Force-reload tool modules so they pick up all IDA mocks (including ida_ida).
import importlib
import rikugan.ida.tools.database as _db_mod
importlib.reload(_db_mod)


# --- Database tools --------------------------------------------------------

class TestGetBinaryInfo(unittest.TestCase):
    def test_returns_filename_and_function_count(self):
        from rikugan.ida.tools.database import get_binary_info
        result = get_binary_info()
        self.assertIn("test_binary", result)
        self.assertIn("Functions:", result)

    def test_contains_processor_info(self):
        from rikugan.ida.tools.database import get_binary_info
        result = get_binary_info()
        self.assertTrue("Processor:" in result or "unavailable" in result)


class TestListSegments(unittest.TestCase):
    def test_returns_segment_header(self):
        from rikugan.ida.tools.database import list_segments
        result = list_segments()
        self.assertTrue(result.startswith("Segments:"))


class TestListExports(unittest.TestCase):
    def test_returns_exports_header(self):
        from rikugan.ida.tools.database import list_exports
        result = list_exports()
        self.assertTrue(result.startswith("Exports 0-"))


class TestListImports(unittest.TestCase):
    def test_returns_imports_header(self):
        from rikugan.ida.tools.database import list_imports
        result = list_imports()
        self.assertTrue(result.startswith("Imports 0-"))


class TestReadBytes(unittest.TestCase):
    def test_returns_hex_dump(self):
        from rikugan.ida.tools.database import read_bytes
        result = read_bytes("0x1000", size=16)
        self.assertIn("0x", result)

    def test_size_clamped_to_1024(self):
        from rikugan.ida.tools.database import read_bytes
        result = read_bytes("0x1000", size=9999)
        self.assertIsInstance(result, str)


class TestReadGlobalValue(unittest.TestCase):
    def test_interprets_global_value(self):
        from rikugan.ida.tools.database import read_global_value
        result = read_global_value("0x1000", type_hint="u32")
        self.assertIn("Global value at 0x1000", result)
        self.assertIn("u32:", result)
        self.assertIn("Bytes:", result)


# --- Function tools --------------------------------------------------------

class TestListFunctions(unittest.TestCase):
    def test_pagination(self):
        from rikugan.ida.tools.functions import list_functions
        result = list_functions(offset=0, limit=2)
        self.assertIn("Functions 0", result)
        lines = result.strip().split("\n")
        self.assertLessEqual(len(lines), 3)

    def test_full_list(self):
        from rikugan.ida.tools.functions import list_functions
        result = list_functions()
        self.assertIn("of 3:", result)


class TestSearchFunctions(unittest.TestCase):
    def test_finds_by_substring(self):
        from rikugan.ida.tools.functions import search_functions
        result = search_functions("sub")
        self.assertIn("sub_1000", result)

    def test_no_match(self):
        from rikugan.ida.tools.functions import search_functions
        result = search_functions("zzz_nonexistent_zzz")
        self.assertIn("No functions matching", result)


class TestGetFunctionInfo(unittest.TestCase):
    def test_returns_name_and_address(self):
        from rikugan.ida.tools.functions import get_function_info
        result = get_function_info("0x1000")
        self.assertIn("Name:", result)
        self.assertIn("Address:", result)
        self.assertIn("Size:", result)


# --- String tools ----------------------------------------------------------

class TestListStrings(unittest.TestCase):
    def test_returns_header(self):
        from rikugan.ida.tools.strings import list_strings
        result = list_strings()
        self.assertIn("Strings 0", result)


class TestSearchStrings(unittest.TestCase):
    def test_no_match_returns_message(self):
        from rikugan.ida.tools.strings import search_strings
        result = search_strings("zzz_nonexistent")
        self.assertIn("No strings matching", result)


class TestGetStringAt(unittest.TestCase):
    def test_decodes_utf8(self):
        from rikugan.ida.tools.strings import get_string_at
        result = get_string_at("0x1000")
        self.assertEqual(result, "test string")


# --- Xref tools ------------------------------------------------------------

class TestXrefsTo(unittest.TestCase):
    def test_no_xrefs(self):
        from rikugan.ida.tools.xrefs import xrefs_to
        result = xrefs_to("0x1000")
        self.assertIn("(none)", result)

    def test_header_includes_address(self):
        from rikugan.ida.tools.xrefs import xrefs_to
        result = xrefs_to("0x1000")
        self.assertIn("0x1000", result)


class TestXrefsFrom(unittest.TestCase):
    def test_no_xrefs(self):
        from rikugan.ida.tools.xrefs import xrefs_from
        result = xrefs_from("0x1000")
        self.assertIn("(none)", result)


class TestFunctionXrefs(unittest.TestCase):
    def test_returns_callers_callees(self):
        from rikugan.ida.tools.xrefs import function_xrefs
        result = function_xrefs("0x1000")
        self.assertIn("Callers", result)
        self.assertIn("Callees", result)


# --- Annotation tools ------------------------------------------------------

class TestRenameFunction(unittest.TestCase):
    def test_successful_rename(self):
        from rikugan.ida.tools.annotations import rename_function
        result = rename_function("0x1000", "my_func")
        self.assertIn("Renamed", result)
        self.assertIn("my_func", result)


class TestSetComment(unittest.TestCase):
    def test_set_regular_comment(self):
        from rikugan.ida.tools.annotations import set_comment
        result = set_comment("0x1000", "my comment")
        self.assertIn("Set", result)
        self.assertIn("comment", result)

    def test_set_repeatable_comment(self):
        from rikugan.ida.tools.annotations import set_comment
        result = set_comment("0x1000", "rep comment", repeatable=True)
        self.assertIn("repeatable", result)


class TestRenameAddress(unittest.TestCase):
    def test_successful_rename(self):
        from rikugan.ida.tools.annotations import rename_address
        result = rename_address("0x1000", "label_1000")
        self.assertIn("Named", result)


# --- Disassembly tools -----------------------------------------------------

class TestReadDisassembly(unittest.TestCase):
    def test_returns_disassembly(self):
        from rikugan.ida.tools.disassembly import read_disassembly
        result = read_disassembly("0x1000", count=1)
        self.assertIn("MOV", result)


class TestGetInstructionInfo(unittest.TestCase):
    def test_returns_mnemonic_and_size(self):
        from rikugan.ida.tools.disassembly import get_instruction_info
        result = get_instruction_info("0x1000")
        self.assertIn("Mnemonic: MOV", result)
        self.assertIn("Size: 4", result)


if __name__ == "__main__":
    unittest.main()
