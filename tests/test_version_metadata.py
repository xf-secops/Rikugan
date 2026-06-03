from __future__ import annotations

import json
from pathlib import Path

from rikugan.constants import PLUGIN_VERSION

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_plugin_version_matches_project_metadata() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    plugin_json = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    ida_plugin_json = json.loads((ROOT / "ida-plugin.json").read_text(encoding="utf-8"))

    assert PLUGIN_VERSION == pyproject["project"]["version"]
    assert PLUGIN_VERSION == plugin_json["version"]
    assert PLUGIN_VERSION == ida_plugin_json["plugin"]["version"]
