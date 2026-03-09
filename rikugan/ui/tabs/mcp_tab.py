"""MCP settings tab: enable/disable Rikugan and external MCP servers."""

from __future__ import annotations

from typing import Dict, List

from ..qt_compat import (
    QCheckBox, QGroupBox, QLabel, QScrollArea, QVBoxLayout, QWidget,
)
from ...core.config import RikuganConfig
from ...core.external_sources import discover_all_external_mcp
from ...core.logging import log_debug, log_error
from ...mcp.config import MCPServerConfig, load_mcp_config


class MCPTab(QWidget):
    """Tab for managing MCP servers: Rikugan configured + external MCP."""

    def __init__(self, config: RikuganConfig, parent: QWidget = None):
        super().__init__(parent)
        self._config = config
        self._rikugan_checks: Dict[str, QCheckBox] = {}
        self._external_checks: Dict[str, QCheckBox] = {}
        self._rikugan_servers: List[MCPServerConfig] = []
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)

        # Rikugan MCP servers
        rikugan_group = self._build_rikugan_group()
        layout.addWidget(rikugan_group)

        # External MCP
        try:
            external = discover_all_external_mcp()
        except Exception as e:
            log_error(f"Failed to discover external MCP: {e}")
            external = {}

        for source_key, servers in sorted(external.items()):
            group = self._build_external_group(source_key, servers)
            layout.addWidget(group)

        layout.addStretch()
        scroll.setWidget(container)
        outer.addWidget(scroll)

    def _build_rikugan_group(self) -> QGroupBox:
        """Build the Rikugan MCP servers group box."""
        group = QGroupBox("Rikugan MCP Servers")
        layout = QVBoxLayout(group)

        try:
            self._rikugan_servers = load_mcp_config(self._config.mcp_config_path)
        except Exception as e:
            log_error(f"Failed to load Rikugan MCP config: {e}")
            self._rikugan_servers = []

        if not self._rikugan_servers:
            layout.addWidget(QLabel("No MCP servers configured"))
            return group

        for server in sorted(self._rikugan_servers, key=lambda s: s.name):
            cb = QCheckBox(f"{server.name}  —  {server.command}")
            cb.setChecked(server.enabled)
            self._rikugan_checks[server.name] = cb
            layout.addWidget(cb)

        return group

    def _build_external_group(self, source_key: str, servers: List[MCPServerConfig]) -> QGroupBox:
        """Build a group box for external MCP servers from one source."""
        if source_key == "claude":
            title = "Claude Code MCP Servers"
        elif source_key == "codex":
            title = "Codex MCP Servers"
        else:
            title = f"{source_key} MCP Servers"

        group = QGroupBox(title)
        layout = QVBoxLayout(group)

        if not servers:
            layout.addWidget(QLabel("No MCP servers found"))
            return group

        enabled_set = set(self._config.enabled_external_mcp)

        for server in sorted(servers, key=lambda s: s.name):
            ext_id = f"{source_key}:{server.name}"
            cb = QCheckBox(f"{server.name}  —  {server.command}")
            cb.setChecked(ext_id in enabled_set)
            self._external_checks[ext_id] = cb
            layout.addWidget(cb)

        return group

    def apply_to_config(self, config: RikuganConfig) -> None:
        """Write checkbox state back to config fields."""
        # Update Rikugan MCP server enabled state
        for server in self._rikugan_servers:
            cb = self._rikugan_checks.get(server.name)
            if cb is not None:
                server.enabled = cb.isChecked()

        # Persist Rikugan MCP config changes
        if self._rikugan_servers:
            try:
                from ...mcp.config import save_mcp_config
                save_mcp_config(self._rikugan_servers, config.mcp_config_path)
            except Exception as e:
                log_error(f"Failed to save MCP config: {e}")

        # Enabled external MCP (checked = enabled)
        config.enabled_external_mcp = [
            ext_id for ext_id, cb in self._external_checks.items()
            if cb.isChecked()
        ]

        log_debug(f"MCP config: {len(config.enabled_external_mcp)} external enabled")
