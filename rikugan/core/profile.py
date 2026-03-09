"""Analysis profiles: control what data reaches the LLM provider."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

from .logging import log_debug

# ---------------------------------------------------------------------------
# IOC filter categories — keys used in AnalysisProfile.ioc_filters
# ---------------------------------------------------------------------------

IOC_FILTER_CATEGORIES: Dict[str, str] = {
    "hashes": "File hashes (MD5, SHA1, SHA256)",
    "ipv4": "IPv4 addresses",
    "ipv6": "IPv6 addresses",
    "domains": "Domain names",
    "urls": "URLs (http/https/ftp)",
    "registry_keys": "Windows registry keys",
    "file_paths": "File paths (Windows & Unix)",
    "emails": "Email addresses",
    "crypto_wallets": "Cryptocurrency wallet addresses",
    "mutexes": "Mutex / named object names",
}


# ---------------------------------------------------------------------------
# Known tool names — used by the UI to populate the denied-tools picker.
# Sorted by category for readability. This list covers both IDA and Binary
# Ninja hosts; tools missing from the active host are silently ignored.
# ---------------------------------------------------------------------------

KNOWN_TOOL_NAMES: Dict[str, List[str]] = {
    "Navigation": [
        "get_cursor_position", "get_current_function", "jump_to",
        "get_name_at", "get_address_of",
    ],
    "Database": [
        "get_binary_info", "list_segments", "list_imports", "list_exports",
        "read_bytes",
    ],
    "Functions": [
        "list_functions", "get_function_info", "search_functions",
    ],
    "Strings": [
        "list_strings", "search_strings", "get_string_at",
    ],
    "Disassembly": [
        "read_disassembly", "read_function_disassembly", "get_instruction_info",
    ],
    "Decompiler": [
        "decompile_function", "get_pseudocode", "get_decompiler_variables",
        "set_pseudocode_comment", "get_pseudocode_comment", "redecompile_function",
    ],
    "Cross-References": [
        "xrefs_to", "xrefs_from", "function_xrefs",
    ],
    "Annotations": [
        "rename_function", "rename_variable", "rename_address",
        "set_comment", "set_function_comment", "set_type",
        "set_function_prototype",
    ],
    "Types": [
        "create_struct", "modify_struct", "get_struct_info", "list_structs",
        "create_enum", "modify_enum", "get_enum_info", "list_enums",
        "create_typedef", "apply_struct_to_address", "apply_type_to_variable",
        "import_c_header", "suggest_struct_from_accesses", "propagate_type",
        "get_type_libraries", "import_type_from_library",
    ],
    "Microcode": [
        "get_microcode", "get_microcode_block", "nop_microcode",
        "install_microcode_optimizer", "remove_microcode_optimizer",
        "list_microcode_optimizers",
    ],
    "Scripting": [
        "execute_python",
    ],
}


@dataclass
class AnalysisProfile:
    """A named analysis profile that controls data filtering and tool access."""

    name: str
    description: str = ""
    denied_tools: List[str] = field(default_factory=list)
    denied_functions: List[str] = field(default_factory=list)
    custom_filters: List[str] = field(default_factory=list)
    hide_binary_metadata: bool = False
    ioc_filters: Dict[str, bool] = field(default_factory=dict)
    custom_filter_rules: List[Dict[str, Any]] = field(default_factory=list)
    singular_analysis: bool = False
    builtin: bool = False

    @property
    def has_any_ioc_filter(self) -> bool:
        """True if any IOC category is enabled or custom filter rules exist."""
        return any(self.ioc_filters.values()) or bool(self.custom_filter_rules)

    @property
    def filter_iocs_in_data(self) -> bool:
        """Backward-compat property — True when any IOC filter is active."""
        return self.has_any_ioc_filter

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict suitable for JSON storage."""
        d = asdict(self)
        # Don't persist the builtin flag — it's derived at load time
        d.pop("builtin", None)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnalysisProfile:
        """Deserialize from a dict."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}

        # Backward compat: old configs have filter_iocs_in_data bool
        if data.get("filter_iocs_in_data") and not data.get("ioc_filters"):
            filtered["ioc_filters"] = {k: True for k in IOC_FILTER_CATEGORIES}
            filtered.pop("filter_iocs_in_data", None)
        elif "filter_iocs_in_data" in filtered:
            filtered.pop("filter_iocs_in_data", None)

        return cls(**filtered)


# ---------------------------------------------------------------------------
# Built-in profiles
# ---------------------------------------------------------------------------

DEFAULT_PROFILE = AnalysisProfile(
    name="default",
    description="Standard analysis mode",
    builtin=True,
)

PRIVATE_PROFILE = AnalysisProfile(
    name="private",
    description="Private malware analysis — no metadata or IOCs leak",
    hide_binary_metadata=True,
    ioc_filters={k: True for k in IOC_FILTER_CATEGORIES},
    singular_analysis=True,
    builtin=True,
)

_BUILTIN_PROFILES: Dict[str, AnalysisProfile] = {
    "default": DEFAULT_PROFILE,
    "private": PRIVATE_PROFILE,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_profile(name: str, custom_profiles: Dict[str, Dict] | None = None) -> AnalysisProfile:
    """Look up a profile by name.

    Checks built-in profiles first, then custom profiles from config.
    Falls back to DEFAULT_PROFILE if not found.
    """
    # Built-in
    if name in _BUILTIN_PROFILES:
        return _BUILTIN_PROFILES[name]

    # Custom
    if custom_profiles and name in custom_profiles:
        data = custom_profiles[name]
        if isinstance(data, dict):
            profile = AnalysisProfile.from_dict(data)
            profile.name = name
            log_debug(f"Loaded custom profile: {name}")
            return profile

    # Fallback
    log_debug(f"Profile '{name}' not found, falling back to default")
    return DEFAULT_PROFILE


def list_profiles(custom_profiles: Dict[str, Dict] | None = None) -> List[AnalysisProfile]:
    """List all available profiles (builtins + custom)."""
    profiles: List[AnalysisProfile] = list(_BUILTIN_PROFILES.values())

    if custom_profiles:
        for name, data in sorted(custom_profiles.items()):
            if name in _BUILTIN_PROFILES:
                continue  # don't override builtins
            if isinstance(data, dict):
                profile = AnalysisProfile.from_dict(data)
                profile.name = name
                profiles.append(profile)

    return profiles
