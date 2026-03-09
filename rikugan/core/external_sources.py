"""Discover skills and MCP configs from external CLI tools (Claude Code, Codex).

Platform notes
--------------
Both Claude Code and Codex use ``~/.claude/`` and ``~/.codex/`` respectively on
**all** platforms (macOS, Linux, Windows).  Python's ``Path.home()`` resolves
``~`` correctly on each OS (``%USERPROFILE%`` on Windows, ``$HOME`` elsewhere).

Codex honours the ``CODEX_HOME`` environment variable as an override for
``~/.codex/``.

Claude Code enterprise/managed MCP configs live in platform-specific paths:

* macOS  — ``/Library/Application Support/ClaudeCode/managed-mcp.json``
* Linux  — ``/etc/claude-code/managed-mcp.json``
* Windows — ``C:\\Program Files\\ClaudeCode\\managed-mcp.json``
"""

from __future__ import annotations

import json
import os
import platform
from pathlib import Path

try:
    import tomllib                      # Python 3.11+
except ModuleNotFoundError:
    try:
        import tomli as tomllib         # pip backport for 3.10 and earlier
    except ModuleNotFoundError:
        tomllib = None                  # type: ignore[assignment]
from typing import Dict, List

from ..core.logging import log_debug, log_info
from ..skills.loader import SkillDefinition, discover_skills
from ..mcp.config import MCPServerConfig


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def get_claude_code_base() -> Path:
    """Return the Claude Code config directory (~/.claude).

    Same path on macOS, Linux, and Windows.
    """
    return Path.home() / ".claude"


def get_codex_base() -> Path:
    """Return the Codex CLI config directory.

    Respects the ``CODEX_HOME`` environment variable; falls back to
    ``~/.codex/``.  Same fallback path on macOS, Linux, and Windows.
    """
    codex_home = os.environ.get("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home)
    return Path.home() / ".codex"


def _get_claude_managed_mcp_path() -> Path | None:
    """Return the platform-specific managed MCP config path, or *None*."""
    system = platform.system()
    if system == "Darwin":
        return Path("/Library/Application Support/ClaudeCode/managed-mcp.json")
    if system == "Linux":
        return Path("/etc/claude-code/managed-mcp.json")
    if system == "Windows":
        return Path(r"C:\Program Files\ClaudeCode\managed-mcp.json")
    return None


# ---------------------------------------------------------------------------
# Skills discovery — reuses discover_skills() from skills/loader.py
# ---------------------------------------------------------------------------

def discover_claude_skills() -> List[SkillDefinition]:
    """Scan ``~/.claude/skills/`` for Claude Code skills."""
    skills_dir = get_claude_code_base() / "skills"
    log_debug(f"Scanning Claude Code skills: {skills_dir}")
    return discover_skills(str(skills_dir))


def discover_codex_skills() -> List[SkillDefinition]:
    """Scan ``~/.codex/skills/`` for Codex skills."""
    skills_dir = get_codex_base() / "skills"
    log_debug(f"Scanning Codex skills: {skills_dir}")
    return discover_skills(str(skills_dir))


def discover_all_external_skills() -> Dict[str, List[SkillDefinition]]:
    """Discover skills from all external sources.

    Returns ``{"claude": [...], "codex": [...]}``.
    """
    result: Dict[str, List[SkillDefinition]] = {}
    result["claude"] = discover_claude_skills()
    log_info(f"External skills: {len(result['claude'])} from Claude Code")
    result["codex"] = discover_codex_skills()
    log_info(f"External skills: {len(result['codex'])} from Codex")
    return result


# ---------------------------------------------------------------------------
# MCP discovery
# ---------------------------------------------------------------------------

def _load_mcp_json(path: Path) -> List[MCPServerConfig]:
    """Load MCP server configs from a JSON file (``mcpServers`` key).

    Returns an empty list if the file doesn't exist or is malformed.
    """
    if not path.is_file():
        log_debug(f"External MCP config not found: {path}")
        return []

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log_debug(f"Failed to load external MCP config {path}: {e}")
        return []

    servers_dict = data.get("mcpServers", {})
    servers: List[MCPServerConfig] = []

    for name, cfg in servers_dict.items():
        if not isinstance(cfg, dict):
            continue
        command = cfg.get("command", "")
        if not command:
            continue
        server = MCPServerConfig(
            name=name,
            command=command,
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            enabled=True,
            timeout=float(cfg.get("timeout", 30.0)),
        )
        servers.append(server)
        log_debug(f"External MCP server: {name} cmd={command}")

    return servers


def _load_codex_mcp_toml(path: Path) -> List[MCPServerConfig]:
    """Load MCP server configs from Codex ``config.toml``.

    Codex stores MCP servers under the ``[mcp_servers]`` TOML table::

        [mcp_servers.my_server]
        command = "node"
        args = ["server.js"]
        env = {PORT = "3000"}
        startup_timeout_sec = 60

    Returns an empty list if the file doesn't exist, is malformed, or if
    no TOML parser is available (``pip install tomli`` for Python < 3.11).
    """
    if tomllib is None:
        log_debug("TOML parser unavailable — skipping Codex config (pip install tomli)")
        return []

    if not path.is_file():
        log_debug(f"Codex config not found: {path}")
        return []

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        log_debug(f"Failed to load Codex config {path}: {e}")
        return []

    mcp_servers = data.get("mcp_servers", {})
    servers: List[MCPServerConfig] = []

    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            continue
        command = cfg.get("command", "")
        if not command:
            continue
        # Codex uses startup_timeout_sec; map to our timeout field
        timeout = float(cfg.get("startup_timeout_sec", cfg.get("timeout", 30.0)))
        server = MCPServerConfig(
            name=name,
            command=command,
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            enabled=True,
            timeout=timeout,
        )
        servers.append(server)
        log_debug(f"External MCP server (Codex): {name} cmd={command}")

    return servers


def load_claude_mcp() -> List[MCPServerConfig]:
    """Load MCP configs from Claude Code.

    Checks (in order, merging & de-duplicating by name, earlier wins):

    1. ``~/.claude/.mcp.json``  — per-project config
    2. ``~/.claude/mcp.json``   — older config location
    3. ``~/.claude.json``       — global Claude config
    4. Platform-specific managed/enterprise MCP config
    """
    base = get_claude_code_base()
    seen_names: set = set()
    servers: List[MCPServerConfig] = []

    # Build candidate list in priority order
    candidates: List[Path] = [
        base / ".mcp.json",                # per-project
        base / "mcp.json",                 # older location
        Path.home() / ".claude.json",      # global user config
    ]
    managed = _get_claude_managed_mcp_path()
    if managed is not None:
        candidates.append(managed)

    for path in candidates:
        if not path.is_file():
            continue
        log_debug(f"Loading Claude Code MCP config: {path}")
        for server in _load_mcp_json(path):
            if server.name not in seen_names:
                seen_names.add(server.name)
                servers.append(server)
            else:
                log_debug(f"Skipping duplicate MCP server '{server.name}' from {path}")

    return servers


def load_codex_mcp() -> List[MCPServerConfig]:
    """Load MCP configs from Codex CLI (``~/.codex/config.toml``)."""
    path = get_codex_base() / "config.toml"
    log_debug(f"Scanning Codex MCP config: {path}")
    return _load_codex_mcp_toml(path)


def discover_all_external_mcp() -> Dict[str, List[MCPServerConfig]]:
    """Discover MCP server configs from all external sources.

    Returns ``{"claude": [...], "codex": [...]}``.
    """
    result: Dict[str, List[MCPServerConfig]] = {}
    result["claude"] = load_claude_mcp()
    log_info(f"External MCP: {len(result['claude'])} servers from Claude Code")
    result["codex"] = load_codex_mcp()
    log_info(f"External MCP: {len(result['codex'])} servers from Codex")
    return result
