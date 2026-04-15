"""Helpers for optional Python dependency detection and UI warnings."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyStatus:
    """Runtime availability for an optional Python package."""

    key: str
    module: str
    package_name: str
    feature: str
    available: bool

    @property
    def warning(self) -> str:
        return f"{self.package_name} missing: {self.feature} will be unavailable (install `{self.package_name}`)."


_OPTIONAL_DEPENDENCIES: tuple[tuple[str, str, str, str], ...] = (
    ("anthropic", "anthropic", "anthropic", "Anthropic models"),
    ("openai", "openai", "openai", "OpenAI and OpenAI-compatible models"),
    ("gemini", "google.genai", "google-genai", "Gemini models"),
    ("mcp", "mcp", "mcp", "MCP server integration"),
    ("cryptography", "cryptography", "cryptography", "encrypted API-key storage"),
    ("ida_domain", "ida_domain", "ida-domain", "advanced IDA scripting skill workflows"),
)


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError, AttributeError):
        return False


def get_optional_dependency_statuses() -> list[DependencyStatus]:
    """Return current availability for optional runtime dependencies."""
    statuses = [
        DependencyStatus(
            key=key,
            module=module,
            package_name=package_name,
            feature=feature,
            available=_module_available(module),
        )
        for key, module, package_name, feature in _OPTIONAL_DEPENDENCIES
    ]

    # Python 3.11+ bundles tomllib, so the tomli backport is only optional there.
    if sys.version_info < (3, 11):
        statuses.append(
            DependencyStatus(
                key="tomli",
                module="tomli",
                package_name="tomli",
                feature="external skills/MCP config discovery on Python 3.10",
                available=_module_available("tomli"),
            )
        )

    return statuses


def get_missing_dependency_warnings() -> list[str]:
    """Return human-readable warnings for missing optional dependencies."""
    return [status.warning for status in get_optional_dependency_statuses() if not status.available]
