"""Profiles settings tab: select and configure analysis profiles."""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from ..qt_compat import (
    QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QLabel,
    QPlainTextEdit, QPushButton, QVBoxLayout, QWidget, QLineEdit,
    QFormLayout, QMessageBox, QListWidget, QListWidgetItem,
    QSplitter, QFrame, QScrollArea, Qt, QSizePolicy,
)
from ...core.config import RikuganConfig
from ...core.logging import log_debug
from ...core.profile import (
    AnalysisProfile, DEFAULT_PROFILE, IOC_FILTER_CATEGORIES, KNOWN_TOOL_NAMES,
    PRIVATE_PROFILE, _BUILTIN_PROFILES, get_profile, list_profiles,
)

_BTN_STYLE = (
    "QPushButton { background: #2d2d2d; color: #d4d4d4; border: 1px solid #3c3c3c; "
    "border-radius: 4px; padding: 4px 12px; font-size: 11px; }"
    "QPushButton:hover { background: #3c3c3c; }"
)

_GROUP_STYLE = (
    "QGroupBox { font-weight: bold; border: 1px solid #3c3c3c; "
    "border-radius: 4px; margin-top: 14px; padding-top: 4px; }"
    "QGroupBox::title { subcontrol-origin: margin; left: 10px; "
    "padding: 0 6px; }"
)


class ProfilesTab(QWidget):
    """Tab for managing analysis profiles."""

    def __init__(self, config: RikuganConfig, parent: QWidget = None):
        super().__init__(parent)
        self._config = config
        self._custom_profiles: Dict[str, Dict] = copy.deepcopy(config.custom_profiles)
        self._build_ui()
        self._load_profile(self._profile_combo.currentText())

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # --- Profile selector + action buttons row ---
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Active Profile:"))
        self._profile_combo = QComboBox()
        self._populate_combo()
        self._profile_combo.currentTextChanged.connect(self._on_profile_changed)
        top_row.addWidget(self._profile_combo, 1)

        self._new_btn = QPushButton("+ New")
        self._new_btn.setStyleSheet(_BTN_STYLE)
        self._new_btn.clicked.connect(self._on_new_profile)
        top_row.addWidget(self._new_btn)

        self._clone_btn = QPushButton("Clone")
        self._clone_btn.setStyleSheet(_BTN_STYLE)
        self._clone_btn.clicked.connect(self._on_clone_profile)
        top_row.addWidget(self._clone_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setStyleSheet(_BTN_STYLE)
        self._delete_btn.clicked.connect(self._on_delete_profile)
        top_row.addWidget(self._delete_btn)

        outer.addLayout(top_row)

        # --- Scrollable content area ---
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(6)

        # ---- Description ----
        desc_group = QGroupBox("Description")
        desc_group.setStyleSheet(_GROUP_STYLE)
        desc_lay = QVBoxLayout(desc_group)
        desc_lay.setContentsMargins(10, 16, 10, 8)
        self._desc_edit = QPlainTextEdit()
        self._desc_edit.setMaximumHeight(60)
        self._desc_edit.setPlaceholderText(
            "Describe this profile's purpose (shown to the AI agent in the system prompt)"
        )
        self._desc_edit.setToolTip(
            "This description is shown to the AI agent in the system prompt.\n"
            "A clear description helps the agent understand and follow your\n"
            "constraints (e.g. 'Private analysis \u2014 never leak sample hashes\n"
            "or reference external threat intelligence')."
        )
        desc_lay.addWidget(self._desc_edit)
        layout.addWidget(desc_group)

        # ---- Behavior checkbox ----
        self._hide_metadata_cb = QCheckBox("Hide binary metadata")
        layout.addWidget(self._hide_metadata_cb)

        # ---- IOC Redaction Filters ----
        ioc_group = QGroupBox("IOC Redaction Filters")
        ioc_group.setStyleSheet(_GROUP_STYLE)
        ioc_outer = QVBoxLayout(ioc_group)
        ioc_outer.setContentsMargins(10, 20, 10, 8)
        ioc_outer.setSpacing(4)

        # Select All / Deselect All row
        ioc_btns = QHBoxLayout()
        ioc_btns.setSpacing(6)
        self._ioc_select_all_btn = QPushButton("Select All")
        self._ioc_select_all_btn.setStyleSheet(_BTN_STYLE)
        self._ioc_select_all_btn.clicked.connect(self._on_ioc_select_all)
        ioc_btns.addWidget(self._ioc_select_all_btn)
        self._ioc_deselect_btn = QPushButton("Deselect All")
        self._ioc_deselect_btn.setStyleSheet(_BTN_STYLE)
        self._ioc_deselect_btn.clicked.connect(self._on_ioc_deselect_all)
        ioc_btns.addWidget(self._ioc_deselect_btn)
        ioc_btns.addStretch()
        ioc_outer.addLayout(ioc_btns)

        # Two-column checkbox grid
        self._ioc_checkboxes: Dict[str, QCheckBox] = {}
        keys = list(IOC_FILTER_CATEGORIES.keys())
        mid = (len(keys) + 1) // 2
        ioc_grid = QHBoxLayout()
        ioc_grid.setSpacing(16)
        for col_keys in (keys[:mid], keys[mid:]):
            col = QVBoxLayout()
            col.setSpacing(3)
            for key in col_keys:
                cb = QCheckBox(IOC_FILTER_CATEGORIES[key])
                self._ioc_checkboxes[key] = cb
                col.addWidget(cb)
            col.addStretch()
            ioc_grid.addLayout(col)
        ioc_outer.addLayout(ioc_grid)
        layout.addWidget(ioc_group)

        # ---- Custom Filter Rules ----
        rules_group = QGroupBox("Custom Filter Rules")
        rules_group.setStyleSheet(_GROUP_STYLE)
        rules_lay = QVBoxLayout(rules_group)
        rules_lay.setContentsMargins(10, 20, 10, 8)
        rules_lay.setSpacing(4)

        # Row 1: name + pattern
        row1 = QHBoxLayout()
        row1.setSpacing(6)
        self._rule_name_edit = QLineEdit()
        self._rule_name_edit.setPlaceholderText("Name")
        self._rule_name_edit.setFixedWidth(120)
        row1.addWidget(self._rule_name_edit)
        self._rule_pattern_edit = QLineEdit()
        self._rule_pattern_edit.setPlaceholderText("Pattern (regex or exact string)")
        row1.addWidget(self._rule_pattern_edit, 1)
        rules_lay.addLayout(row1)

        # Row 2: type + replacement + Add button
        row2 = QHBoxLayout()
        row2.setSpacing(6)
        self._rule_type_combo = QComboBox()
        self._rule_type_combo.addItems(["Regex", "Exact"])
        self._rule_type_combo.setFixedWidth(80)
        row2.addWidget(self._rule_type_combo)
        self._rule_replacement_edit = QLineEdit()
        self._rule_replacement_edit.setPlaceholderText("Replacement (default: [CUSTOM_REDACTED])")
        row2.addWidget(self._rule_replacement_edit, 1)
        self._add_rule_btn = QPushButton("+ Add")
        self._add_rule_btn.setStyleSheet(_BTN_STYLE)
        self._add_rule_btn.setMinimumWidth(70)
        self._add_rule_btn.clicked.connect(self._on_add_rule)
        row2.addWidget(self._add_rule_btn)
        rules_lay.addLayout(row2)

        # Rules list + Remove button
        list_row = QHBoxLayout()
        list_row.setSpacing(6)
        self._rules_list = QListWidget()
        self._rules_list.setMaximumHeight(72)
        list_row.addWidget(self._rules_list, 1)

        self._remove_rule_btn = QPushButton("Remove")
        self._remove_rule_btn.setStyleSheet(_BTN_STYLE)
        self._remove_rule_btn.setMinimumWidth(70)
        self._remove_rule_btn.clicked.connect(self._on_remove_rule)
        list_row.addWidget(self._remove_rule_btn)
        rules_lay.addLayout(list_row)
        layout.addWidget(rules_group)

        # ---- Denied Tools ----
        tools_group = QGroupBox("Denied Tools")
        tools_group.setStyleSheet(_GROUP_STYLE)
        tools_lay = QVBoxLayout(tools_group)
        tools_lay.setContentsMargins(10, 20, 10, 8)
        tools_lay.setSpacing(4)

        tools_scroll = QScrollArea()
        tools_scroll.setWidgetResizable(True)
        tools_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tools_scroll.setFixedHeight(140)
        tools_inner = QWidget()
        tools_grid = QHBoxLayout(tools_inner)
        tools_grid.setContentsMargins(0, 0, 0, 0)
        tools_grid.setSpacing(12)

        self._denied_tool_cbs: Dict[str, QCheckBox] = {}
        categories = list(KNOWN_TOOL_NAMES.items())
        n_cols = 3
        cols: List[QVBoxLayout] = []
        for _ in range(n_cols):
            c = QVBoxLayout()
            c.setSpacing(2)
            cols.append(c)
            tools_grid.addLayout(c)

        col_idx = 0
        for cat_name, tool_names in categories:
            col = cols[col_idx % n_cols]
            header = QLabel(f"<b>{cat_name}</b>")
            header.setStyleSheet("font-size: 10px; color: #888; margin-top: 6px;")
            col.addWidget(header)
            for tname in tool_names:
                cb = QCheckBox(tname)
                cb.setStyleSheet("font-size: 11px;")
                self._denied_tool_cbs[tname] = cb
                col.addWidget(cb)
            col_idx += 1

        for c in cols:
            c.addStretch()

        tools_scroll.setWidget(tools_inner)
        tools_lay.addWidget(tools_scroll)
        layout.addWidget(tools_group)

        # ---- Advanced ----
        adv_group = QGroupBox("Advanced")
        adv_group.setStyleSheet(_GROUP_STYLE)
        adv_form = QFormLayout(adv_group)
        adv_form.setContentsMargins(10, 20, 10, 8)
        adv_form.setSpacing(6)

        self._denied_funcs_edit = QPlainTextEdit()
        self._denied_funcs_edit.setMaximumHeight(48)
        self._denied_funcs_edit.setPlaceholderText("One function name per line (binary-specific)")
        adv_form.addRow("Denied Functions:", self._denied_funcs_edit)

        self._custom_filters_edit = QPlainTextEdit()
        self._custom_filters_edit.setMaximumHeight(48)
        self._custom_filters_edit.setPlaceholderText("Custom prompt instructions (one per line)")
        adv_form.addRow("Prompt Filters:", self._custom_filters_edit)

        layout.addWidget(adv_group)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    # ------------------------------------------------------------------
    # IOC select/deselect helpers
    # ------------------------------------------------------------------

    def _on_ioc_select_all(self) -> None:
        for cb in self._ioc_checkboxes.values():
            if cb.isEnabled():
                cb.setChecked(True)

    def _on_ioc_deselect_all(self) -> None:
        for cb in self._ioc_checkboxes.values():
            if cb.isEnabled():
                cb.setChecked(False)

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def _populate_combo(self) -> None:
        self._profile_combo.blockSignals(True)
        self._profile_combo.clear()
        for p in list_profiles(self._custom_profiles):
            self._profile_combo.addItem(p.name)
        idx = self._profile_combo.findText(self._config.active_profile)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)
        self._profile_combo.blockSignals(False)

    def _on_profile_changed(self, name: str) -> None:
        self._save_current_to_working_copy()
        self._load_profile(name)

    def _load_profile(self, name: str) -> None:
        profile = get_profile(name, self._custom_profiles)
        is_builtin = name in _BUILTIN_PROFILES

        self._desc_edit.setPlainText(profile.description or "")
        self._hide_metadata_cb.setChecked(profile.hide_binary_metadata)

        # Denied tools checkboxes
        denied_set = set(profile.denied_tools)
        for tname, cb in self._denied_tool_cbs.items():
            cb.setChecked(tname in denied_set)
            cb.setEnabled(not is_builtin)

        self._denied_funcs_edit.setPlainText("\n".join(profile.denied_functions))
        self._custom_filters_edit.setPlainText("\n".join(profile.custom_filters))

        for key, cb in self._ioc_checkboxes.items():
            cb.setChecked(profile.ioc_filters.get(key, False))
            cb.setEnabled(not is_builtin)

        self._rules_list.clear()
        for rule in profile.custom_filter_rules:
            label = rule.get("name", "?")
            kind = "regex" if rule.get("is_regex") else "exact"
            pattern = rule.get("pattern", "")
            self._rules_list.addItem(f"{label} \u2014 {kind}: {pattern}")

        # Read-only state for builtins
        self._desc_edit.setReadOnly(is_builtin)
        self._hide_metadata_cb.setEnabled(not is_builtin)
        self._denied_funcs_edit.setReadOnly(is_builtin)
        self._custom_filters_edit.setReadOnly(is_builtin)
        self._delete_btn.setEnabled(not is_builtin)
        self._add_rule_btn.setEnabled(not is_builtin)
        self._remove_rule_btn.setEnabled(not is_builtin)
        self._rule_name_edit.setEnabled(not is_builtin)
        self._rule_pattern_edit.setEnabled(not is_builtin)
        self._rule_type_combo.setEnabled(not is_builtin)
        self._rule_replacement_edit.setEnabled(not is_builtin)
        self._ioc_select_all_btn.setEnabled(not is_builtin)
        self._ioc_deselect_btn.setEnabled(not is_builtin)

    def _get_current_rules(self) -> List[Dict[str, Any]]:
        name = self._profile_combo.currentText()
        if not name:
            return []
        profile = get_profile(name, self._custom_profiles)
        return list(profile.custom_filter_rules)

    def _save_current_to_working_copy(self) -> None:
        name = self._profile_combo.currentText()
        if not name or name in _BUILTIN_PROFILES:
            return

        ioc_filters = {key: cb.isChecked() for key, cb in self._ioc_checkboxes.items()}
        denied_tools = [tn for tn, cb in self._denied_tool_cbs.items() if cb.isChecked()]
        profile = AnalysisProfile(
            name=name,
            description=self._desc_edit.toPlainText().strip(),
            hide_binary_metadata=self._hide_metadata_cb.isChecked(),
            ioc_filters=ioc_filters,
            custom_filter_rules=self._get_current_rules(),
            denied_tools=denied_tools,
            denied_functions=_text_to_lines(self._denied_funcs_edit.toPlainText()),
            custom_filters=_text_to_lines(self._custom_filters_edit.toPlainText()),
        )
        self._custom_profiles[name] = profile.to_dict()

    # ------------------------------------------------------------------
    # Custom filter rules
    # ------------------------------------------------------------------

    def _on_add_rule(self) -> None:
        rule_name = self._rule_name_edit.text().strip()
        pattern = self._rule_pattern_edit.text().strip()
        if not rule_name or not pattern:
            return

        is_regex = self._rule_type_combo.currentText() == "Regex"
        replacement = self._rule_replacement_edit.text().strip() or "[CUSTOM_REDACTED]"

        rule: Dict[str, Any] = {
            "name": rule_name, "pattern": pattern,
            "is_regex": is_regex, "replacement": replacement,
        }

        name = self._profile_combo.currentText()
        if not name or name in _BUILTIN_PROFILES:
            return

        profile_data = self._custom_profiles.get(name, {})
        rules = list(profile_data.get("custom_filter_rules", []))
        rules.append(rule)
        profile_data["custom_filter_rules"] = rules
        self._custom_profiles[name] = profile_data

        kind = "regex" if is_regex else "exact"
        self._rules_list.addItem(f"{rule_name} \u2014 {kind}: {pattern}")

        self._rule_name_edit.clear()
        self._rule_pattern_edit.clear()
        self._rule_replacement_edit.clear()

    def _on_remove_rule(self) -> None:
        row = self._rules_list.currentRow()
        if row < 0:
            return
        name = self._profile_combo.currentText()
        if not name or name in _BUILTIN_PROFILES:
            return
        profile_data = self._custom_profiles.get(name, {})
        rules = list(profile_data.get("custom_filter_rules", []))
        if 0 <= row < len(rules):
            rules.pop(row)
            profile_data["custom_filter_rules"] = rules
            self._custom_profiles[name] = profile_data
        self._rules_list.takeItem(row)

    # ------------------------------------------------------------------
    # New / Clone / Delete
    # ------------------------------------------------------------------

    def _on_new_profile(self) -> None:
        result = self._prompt_new_profile("New Profile")
        if not result:
            return
        name, desc = result
        if name in _BUILTIN_PROFILES or name in self._custom_profiles:
            QMessageBox.warning(self, "Error", f"Profile '{name}' already exists.")
            return
        p = AnalysisProfile(name=name, description=desc)
        self._custom_profiles[name] = p.to_dict()
        self._populate_combo()
        idx = self._profile_combo.findText(name)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)

    def _on_clone_profile(self) -> None:
        current = self._profile_combo.currentText()
        if not current:
            return
        result = self._prompt_new_profile("Clone Profile")
        if not result:
            return
        name, desc = result
        if name in _BUILTIN_PROFILES or name in self._custom_profiles:
            QMessageBox.warning(self, "Error", f"Profile '{name}' already exists.")
            return
        self._save_current_to_working_copy()
        profile = get_profile(current, self._custom_profiles)
        cloned = AnalysisProfile(
            name=name,
            description=desc or profile.description,
            hide_binary_metadata=profile.hide_binary_metadata,
            ioc_filters=dict(profile.ioc_filters),
            custom_filter_rules=copy.deepcopy(profile.custom_filter_rules),
            denied_tools=list(profile.denied_tools),
            denied_functions=list(profile.denied_functions),
            custom_filters=list(profile.custom_filters),
        )
        self._custom_profiles[name] = cloned.to_dict()
        self._populate_combo()
        idx = self._profile_combo.findText(name)
        if idx >= 0:
            self._profile_combo.setCurrentIndex(idx)

    def _on_delete_profile(self) -> None:
        name = self._profile_combo.currentText()
        if not name or name in _BUILTIN_PROFILES:
            return
        reply = QMessageBox.question(
            self, "Delete Profile", f"Delete profile '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._custom_profiles.pop(name, None)
        self._populate_combo()

    def _prompt_new_profile(self, title: str) -> Optional[tuple]:
        """Prompt for name + description. Returns (name, description) or None."""
        from ..qt_compat import QDialog, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(400)
        lay = QVBoxLayout(dlg)

        form = QFormLayout()
        name_edit = QLineEdit()
        name_edit.setPlaceholderText("e.g. my-custom-profile")
        form.addRow("Name:", name_edit)

        desc_edit = QPlainTextEdit()
        desc_edit.setMaximumHeight(60)
        desc_edit.setPlaceholderText(
            "Describe the profile's purpose (shown to the AI agent)"
        )
        form.addRow("Description:", desc_edit)
        lay.addLayout(form)

        error_label = QLabel()
        error_label.setStyleSheet("color: #f44747; font-size: 11px;")
        error_label.hide()
        lay.addWidget(error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        lay.addWidget(buttons)

        def _validate():
            n = name_edit.text().strip().lower().replace(" ", "-")
            d = desc_edit.toPlainText().strip()
            if not n:
                error_label.setText("Name is required")
                error_label.show()
                return
            if not d:
                error_label.setText("Description is required \u2014 it helps the AI agent follow your constraints")
                error_label.show()
                return
            name_edit.setText(n)
            dlg.accept()

        buttons.accepted.connect(_validate)
        buttons.rejected.connect(dlg.reject)

        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None

        name = name_edit.text().strip()
        desc = desc_edit.toPlainText().strip()
        return (name, desc) if name else None

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def apply_to_config(self, config: RikuganConfig) -> None:
        self._save_current_to_working_copy()
        config.active_profile = self._profile_combo.currentText() or "default"
        config.custom_profiles = copy.deepcopy(self._custom_profiles)
        log_debug(f"Profiles config: active={config.active_profile}, "
                  f"{len(config.custom_profiles)} custom")


def _text_to_lines(text: str) -> List[str]:
    """Split multiline text into non-empty stripped lines."""
    return [line.strip() for line in text.splitlines() if line.strip()]
