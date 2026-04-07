"""Tests for rikugan.ui.qt_compat — Qt compatibility shim."""

from __future__ import annotations

import ast
from pathlib import Path
import unittest

from tests.qt_stubs import ensure_pyside6_stubs

ensure_pyside6_stubs()
import rikugan.ui.qt_compat as qt_compat  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UI_ROOT = _REPO_ROOT / "rikugan" / "ui"


class TestQtCompat(unittest.TestCase):
    def test_is_pyside6_returns_true(self):
        self.assertTrue(qt_compat.is_pyside6())

    def test_qt_binding_constant(self):
        self.assertEqual(qt_compat.QT_BINDING, "PySide6")

    def test_qt_core_symbols_exported(self):
        for name in ("Signal", "Qt", "QObject", "QTimer"):
            self.assertTrue(hasattr(qt_compat, name), f"missing {name}")
        self.assertTrue(qt_compat.is_pyside6())

    def test_qt_widget_symbols_exported(self):
        for name in (
            "QApplication", "QWidget", "QVBoxLayout", "QHBoxLayout",
            "QLabel", "QPushButton", "QPlainTextEdit", "QScrollArea",
            "QDialog", "QComboBox", "QLineEdit", "QCheckBox",
            "QMenu", "QMessageBox",
        ):
            self.assertTrue(hasattr(qt_compat, name), f"missing {name}")

    def test_qt_flags_rejects_mixed_flag_types(self):
        class _FlagA:
            def __init__(self, value: int):
                self.value = value

        class _FlagB:
            def __init__(self, value: int):
                self.value = value

        with self.assertRaises(TypeError):
            qt_compat.qt_flags(_FlagA(1), _FlagB(2))

    def test_target_ui_files_do_not_use_exec_legacy_or_qt_flag_bitwise_or(self):
        offenders: list[str] = []
        for path in sorted(_UI_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(), filename=str(path))
            relative_path = path.relative_to(_REPO_ROOT)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "exec_":
                    offenders.append(f"{relative_path}:{node.lineno}:exec_()")
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
                    segment = ast.get_source_segment(path.read_text(), node) or ""
                    if "Qt." in segment:
                        offenders.append(f"{relative_path}:{node.lineno}:{segment}")
        self.assertEqual([], offenders)


if __name__ == "__main__":
    unittest.main()
