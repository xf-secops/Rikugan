"""Skills settings tab: enable/disable Rikugan, Claude Code, and Codex skills."""

from __future__ import annotations

from typing import Dict, List, Optional

from ..qt_compat import (
    QCheckBox, QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from ...core.config import RikuganConfig
from ...core.external_sources import discover_all_external_skills
from ...core.logging import log_debug, log_error
from ...skills.loader import SkillDefinition


class SkillsTab(QWidget):
    """Tab for managing skills: Rikugan built-in/user skills + external skills."""

    def __init__(self, config: RikuganConfig, parent: QWidget = None):
        super().__init__(parent)
        self._config = config
        self._rikugan_checks: Dict[str, QCheckBox] = {}
        self._external_checks: Dict[str, QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        # Rikugan skills
        rikugan_group = self._build_rikugan_group()
        layout.addWidget(rikugan_group)

        # External skills
        try:
            external = discover_all_external_skills()
        except Exception as e:
            log_error(f"Failed to discover external skills: {e}")
            external = {}

        for source_key, skills in sorted(external.items()):
            group = self._build_external_group(source_key, skills)
            layout.addWidget(group)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_rikugan_group(self) -> QGroupBox:
        """Build the Rikugan skills group box."""
        from ...skills.registry import SkillRegistry

        group = QGroupBox("Rikugan Skills")
        layout = QVBoxLayout(group)

        try:
            registry = SkillRegistry(self._config.skills_dir)
            registry.discover()
            skills = registry.list_skills()
        except Exception as e:
            log_error(f"Failed to discover Rikugan skills: {e}")
            skills = []

        disabled_set = set(self._config.disabled_skills)

        if not skills:
            layout.addWidget(QLabel("No skills found"))
            return group

        for skill in sorted(skills, key=lambda s: s.slug):
            cb = QCheckBox(f"{skill.slug}  —  {skill.description or '(no description)'}")
            cb.setChecked(skill.slug not in disabled_set)
            self._rikugan_checks[skill.slug] = cb
            layout.addWidget(cb)

        return group

    def _build_external_group(self, source_key: str, skills: List[SkillDefinition]) -> QGroupBox:
        """Build a group box for external skills from one source."""
        if source_key == "claude":
            title = "Claude Code Skills (~/.claude/skills/)"
        elif source_key == "codex":
            title = "Codex Skills (~/.codex/skills/)"
        else:
            title = f"{source_key} Skills"

        group = QGroupBox(title)
        layout = QVBoxLayout(group)

        if not skills:
            layout.addWidget(QLabel("No skills found"))
            return group

        enabled_set = set(self._config.enabled_external_skills)

        for skill in sorted(skills, key=lambda s: s.slug):
            ext_id = f"{source_key}:{skill.slug}"
            cb = QCheckBox(f"{skill.slug}  —  {skill.description or '(no description)'}")
            cb.setChecked(ext_id in enabled_set)
            self._external_checks[ext_id] = cb
            layout.addWidget(cb)

        return group

    def apply_to_config(self, config: RikuganConfig) -> None:
        """Write checkbox state back to config fields."""
        # Disabled Rikugan skills (unchecked = disabled)
        config.disabled_skills = [
            slug for slug, cb in self._rikugan_checks.items()
            if not cb.isChecked()
        ]

        # Enabled external skills (checked = enabled)
        config.enabled_external_skills = [
            ext_id for ext_id, cb in self._external_checks.items()
            if cb.isChecked()
        ]

        log_debug(
            f"Skills config: {len(config.disabled_skills)} disabled, "
            f"{len(config.enabled_external_skills)} external enabled"
        )
