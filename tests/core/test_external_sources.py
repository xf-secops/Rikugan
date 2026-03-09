"""Tests for rikugan.core.external_sources — external skill/MCP discovery."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tests.mocks.ida_mock import install_ida_mocks
install_ida_mocks()

from rikugan.core.external_sources import (
    get_claude_code_base,
    get_codex_base,
    discover_claude_skills,
    discover_codex_skills,
    discover_all_external_skills,
    load_claude_mcp,
    load_codex_mcp,
    discover_all_external_mcp,
    _load_mcp_json,
    _load_codex_mcp_toml,
    _get_claude_managed_mcp_path,
)


class TestPathResolution(unittest.TestCase):
    def test_claude_code_base(self):
        base = get_claude_code_base()
        self.assertEqual(base, Path.home() / ".claude")

    def test_codex_base_default(self):
        """Default codex base is ~/.codex."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove CODEX_HOME if present
            env = os.environ.copy()
            env.pop("CODEX_HOME", None)
            with patch.dict(os.environ, env, clear=True):
                base = get_codex_base()
                self.assertEqual(base, Path.home() / ".codex")

    def test_codex_base_codex_home_env(self):
        """CODEX_HOME env var overrides default path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"CODEX_HOME": tmpdir}):
                base = get_codex_base()
                self.assertEqual(base, Path(tmpdir))

    def test_codex_base_codex_home_empty(self):
        """Empty CODEX_HOME falls back to default."""
        with patch.dict(os.environ, {"CODEX_HOME": ""}):
            base = get_codex_base()
            self.assertEqual(base, Path.home() / ".codex")


class TestManagedPaths(unittest.TestCase):
    def test_managed_macos(self):
        with patch("rikugan.core.external_sources.platform.system", return_value="Darwin"):
            path = _get_claude_managed_mcp_path()
            self.assertEqual(path, Path("/Library/Application Support/ClaudeCode/managed-mcp.json"))

    def test_managed_linux(self):
        with patch("rikugan.core.external_sources.platform.system", return_value="Linux"):
            path = _get_claude_managed_mcp_path()
            self.assertEqual(path, Path("/etc/claude-code/managed-mcp.json"))

    def test_managed_windows(self):
        with patch("rikugan.core.external_sources.platform.system", return_value="Windows"):
            path = _get_claude_managed_mcp_path()
            self.assertEqual(path, Path(r"C:\Program Files\ClaudeCode\managed-mcp.json"))

    def test_managed_unknown(self):
        with patch("rikugan.core.external_sources.platform.system", return_value="FreeBSD"):
            path = _get_claude_managed_mcp_path()
            self.assertIsNone(path)


class TestSkillDiscovery(unittest.TestCase):
    def test_discover_from_temp_dir(self):
        """Discover skills from a temporary directory with a valid skill."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # discover_claude_skills() looks in <base>/skills/<slug>/SKILL.md
            skills_root = os.path.join(tmpdir, "skills")
            skill_dir = os.path.join(skills_root, "test-skill")
            os.makedirs(skill_dir)
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write("---\nname: Test Skill\ndescription: A test skill\n---\nBody content.\n")

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=Path(tmpdir)):
                skills = discover_claude_skills()
                self.assertEqual(len(skills), 1)
                self.assertEqual(skills[0].name, "Test Skill")

    def test_discover_missing_dir(self):
        """Missing skills directory returns empty list."""
        with patch("rikugan.core.external_sources.get_claude_code_base", return_value=Path("/nonexistent")):
            skills = discover_claude_skills()
            self.assertEqual(skills, [])

    def test_discover_codex_skills(self):
        """Codex skills discovery works the same way."""
        with patch("rikugan.core.external_sources.get_codex_base", return_value=Path("/nonexistent")):
            skills = discover_codex_skills()
            self.assertEqual(skills, [])

    def test_discover_all_external_skills(self):
        """Aggregate discovery returns dict with both sources."""
        with patch("rikugan.core.external_sources.get_claude_code_base", return_value=Path("/nonexistent")):
            with patch("rikugan.core.external_sources.get_codex_base", return_value=Path("/nonexistent")):
                result = discover_all_external_skills()
                self.assertIn("claude", result)
                self.assertIn("codex", result)
                self.assertEqual(result["claude"], [])
                self.assertEqual(result["codex"], [])


class TestMCPDiscoveryJSON(unittest.TestCase):
    def test_load_valid_mcp_json(self):
        """Load a valid mcp.json file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp_path = Path(tmpdir) / "mcp.json"
            data = {
                "mcpServers": {
                    "test-server": {
                        "command": "node",
                        "args": ["server.js"],
                        "env": {"PORT": "3000"},
                    }
                }
            }
            with open(mcp_path, "w") as f:
                json.dump(data, f)

            servers = _load_mcp_json(mcp_path)
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].name, "test-server")
            self.assertEqual(servers[0].command, "node")
            self.assertEqual(servers[0].args, ["server.js"])

    def test_load_missing_file(self):
        """Missing file returns empty list."""
        servers = _load_mcp_json(Path("/nonexistent/mcp.json"))
        self.assertEqual(servers, [])

    def test_load_malformed_json(self):
        """Malformed JSON returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp_path = Path(tmpdir) / "mcp.json"
            with open(mcp_path, "w") as f:
                f.write("{invalid json")
            servers = _load_mcp_json(mcp_path)
            self.assertEqual(servers, [])

    def test_load_no_command_skipped(self):
        """Servers without a command are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mcp_path = Path(tmpdir) / "mcp.json"
            data = {
                "mcpServers": {
                    "no-cmd": {"args": ["x"]},
                    "has-cmd": {"command": "python", "args": ["-m", "server"]},
                }
            }
            with open(mcp_path, "w") as f:
                json.dump(data, f)
            servers = _load_mcp_json(mcp_path)
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].name, "has-cmd")


class TestMCPDiscoveryTOML(unittest.TestCase):
    """Test Codex TOML-based MCP config parsing."""

    def test_load_valid_codex_toml(self):
        """Load MCP servers from a valid config.toml."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_path.write_text(
                '[mcp_servers.my_server]\n'
                'command = "node"\n'
                'args = ["server.js", "--port", "3000"]\n'
                '\n'
                '[mcp_servers.another]\n'
                'command = "python"\n'
                'args = ["-m", "mcp_server"]\n'
                'startup_timeout_sec = 120\n'
            )
            servers = _load_codex_mcp_toml(toml_path)
            self.assertEqual(len(servers), 2)
            names = {s.name for s in servers}
            self.assertIn("my_server", names)
            self.assertIn("another", names)

            another = next(s for s in servers if s.name == "another")
            self.assertEqual(another.command, "python")
            self.assertEqual(another.args, ["-m", "mcp_server"])
            self.assertEqual(another.timeout, 120.0)

    def test_load_toml_no_mcp_section(self):
        """TOML file without [mcp_servers] returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_path.write_text('model = "gpt-4"\n')
            servers = _load_codex_mcp_toml(toml_path)
            self.assertEqual(servers, [])

    def test_load_toml_missing_file(self):
        servers = _load_codex_mcp_toml(Path("/nonexistent/config.toml"))
        self.assertEqual(servers, [])

    def test_load_toml_malformed(self):
        """Malformed TOML returns empty list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_path.write_text("[invalid toml\nno closing bracket")
            servers = _load_codex_mcp_toml(toml_path)
            self.assertEqual(servers, [])

    def test_load_toml_no_command_skipped(self):
        """Servers without command are skipped in TOML too."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_path.write_text(
                '[mcp_servers.no_cmd]\n'
                'args = ["x"]\n'
                '\n'
                '[mcp_servers.has_cmd]\n'
                'command = "node"\n'
                'args = ["y"]\n'
            )
            servers = _load_codex_mcp_toml(toml_path)
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].name, "has_cmd")

    def test_load_toml_with_env(self):
        """TOML server with env dict is parsed correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            toml_path = Path(tmpdir) / "config.toml"
            toml_path.write_text(
                '[mcp_servers.srv]\n'
                'command = "node"\n'
                'args = ["srv.js"]\n'
                '[mcp_servers.srv.env]\n'
                'PORT = "3000"\n'
                'DEBUG = "1"\n'
            )
            servers = _load_codex_mcp_toml(toml_path)
            self.assertEqual(len(servers), 1)
            self.assertEqual(servers[0].env, {"PORT": "3000", "DEBUG": "1"})

    def test_load_codex_mcp_uses_toml(self):
        """load_codex_mcp() reads config.toml, not mcp.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            toml_path = base / "config.toml"
            toml_path.write_text(
                '[mcp_servers.toml_srv]\n'
                'command = "node"\n'
            )
            # Also create a mcp.json to prove it's ignored
            json_path = base / "mcp.json"
            with open(json_path, "w") as f:
                json.dump({"mcpServers": {"json_srv": {"command": "python"}}}, f)

            with patch("rikugan.core.external_sources.get_codex_base", return_value=base):
                servers = load_codex_mcp()
                self.assertEqual(len(servers), 1)
                self.assertEqual(servers[0].name, "toml_srv")


class TestClaudeMCPMerge(unittest.TestCase):
    def test_claude_mcp_preferred_path(self):
        """Claude Code checks .mcp.json first, merges with mcp.json (deduped)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            preferred = base / ".mcp.json"
            fallback = base / "mcp.json"
            with open(preferred, "w") as f:
                json.dump({"mcpServers": {"preferred": {"command": "node"}}}, f)
            with open(fallback, "w") as f:
                json.dump({"mcpServers": {"fallback": {"command": "python"}}}, f)

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    servers = load_claude_mcp()
                    self.assertEqual(len(servers), 2)
                    names = {s.name for s in servers}
                    self.assertIn("preferred", names)
                    self.assertIn("fallback", names)

    def test_claude_mcp_preferred_path_dedup(self):
        """Duplicate server names across files: earlier file wins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            preferred = base / ".mcp.json"
            fallback = base / "mcp.json"
            with open(preferred, "w") as f:
                json.dump({"mcpServers": {"srv": {"command": "node"}}}, f)
            with open(fallback, "w") as f:
                json.dump({"mcpServers": {"srv": {"command": "python"}}}, f)

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    servers = load_claude_mcp()
                    self.assertEqual(len(servers), 1)
                    self.assertEqual(servers[0].name, "srv")
                    self.assertEqual(servers[0].command, "node")  # preferred wins

    def test_claude_mcp_fallback_path(self):
        """Falls back to mcp.json when .mcp.json doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            fallback = base / "mcp.json"
            with open(fallback, "w") as f:
                json.dump({"mcpServers": {"fallback": {"command": "python"}}}, f)

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    servers = load_claude_mcp()
                    self.assertEqual(len(servers), 1)
                    self.assertEqual(servers[0].name, "fallback")

    def test_claude_mcp_global_claude_json(self):
        """Picks up MCP servers from ~/.claude.json (global config)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            global_cfg = base / ".claude.json"
            with open(global_cfg, "w") as f:
                json.dump({"mcpServers": {"global-srv": {"command": "node", "args": ["srv.js"]}}}, f)

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    servers = load_claude_mcp()
                    self.assertEqual(len(servers), 1)
                    self.assertEqual(servers[0].name, "global-srv")

    def test_claude_mcp_managed_included(self):
        """Managed MCP config is included when file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            managed_path = base / "managed-mcp.json"
            with open(managed_path, "w") as f:
                json.dump({"mcpServers": {"managed-srv": {"command": "node"}}}, f)

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    with patch("rikugan.core.external_sources._get_claude_managed_mcp_path", return_value=managed_path):
                        servers = load_claude_mcp()
                        self.assertEqual(len(servers), 1)
                        self.assertEqual(servers[0].name, "managed-srv")

    def test_claude_mcp_all_sources_merge(self):
        """All 4 sources merge correctly with dedup."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            # Source 1: .mcp.json
            (base / ".mcp.json").write_text(json.dumps(
                {"mcpServers": {"s1": {"command": "a"}, "dup": {"command": "first"}}}
            ))
            # Source 2: mcp.json
            (base / "mcp.json").write_text(json.dumps(
                {"mcpServers": {"s2": {"command": "b"}, "dup": {"command": "second"}}}
            ))
            # Source 3: .claude.json
            (base / ".claude.json").write_text(json.dumps(
                {"mcpServers": {"s3": {"command": "c"}}}
            ))
            # Source 4: managed
            managed_path = base / "managed.json"
            managed_path.write_text(json.dumps(
                {"mcpServers": {"s4": {"command": "d"}}}
            ))

            with patch("rikugan.core.external_sources.get_claude_code_base", return_value=base):
                with patch("rikugan.core.external_sources.Path.home", return_value=base):
                    with patch("rikugan.core.external_sources._get_claude_managed_mcp_path", return_value=managed_path):
                        servers = load_claude_mcp()
                        names = {s.name for s in servers}
                        self.assertEqual(names, {"s1", "s2", "s3", "s4", "dup"})
                        # dup should use "first" (from .mcp.json)
                        dup = next(s for s in servers if s.name == "dup")
                        self.assertEqual(dup.command, "first")


class TestAggregateDiscovery(unittest.TestCase):
    def test_discover_all_external_mcp(self):
        """Aggregate MCP discovery returns dict with both sources."""
        with patch("rikugan.core.external_sources.get_claude_code_base", return_value=Path("/nonexistent")):
            with patch("rikugan.core.external_sources.get_codex_base", return_value=Path("/nonexistent")):
                with patch("rikugan.core.external_sources.Path.home", return_value=Path("/nonexistent")):
                    result = discover_all_external_mcp()
                    self.assertIn("claude", result)
                    self.assertIn("codex", result)


if __name__ == "__main__":
    unittest.main()
