"""Global constants for Rikugan."""

from __future__ import annotations

import importlib

from .core.host import is_binary_ninja, is_ida

PLUGIN_NAME = "Rikugan"
PLUGIN_VERSION = "0.1.0"
PLUGIN_HOTKEY = "Ctrl+Shift+I"
PLUGIN_COMMENT = "Intelligent Reverse-engineering Integrated System"

CONFIG_DIR_NAME = "rikugan"
CONFIG_FILE_NAME = "config.json"
CHECKPOINTS_DIR_NAME = "checkpoints"

DEFAULT_MAX_TOKENS = 16384
DEFAULT_TEMPERATURE = 0.2
DEFAULT_CONTEXT_WINDOW = 200000

TOOL_RESULT_TRUNCATE_LEN = 8000

SYSTEM_PROMPT_VERSION = 1
CONFIG_SCHEMA_VERSION = 2
SESSION_SCHEMA_VERSION = 1

SKILLS_DIR_NAME = "skills"
MCP_CONFIG_FILE = "mcp.json"
MCP_TOOL_PREFIX = "mcp_"
MCP_DEFAULT_TIMEOUT = 30.0

# Runtime host flags
IDA_AVAILABLE = is_ida()
BINARY_NINJA_AVAILABLE = is_binary_ninja()

# Whether the Hex-Rays decompiler SDK is importable.
if IDA_AVAILABLE:
    try:
        importlib.import_module("ida_hexrays")
        HAS_HEXRAYS = True
    except ImportError:
        HAS_HEXRAYS = False
else:
    HAS_HEXRAYS = False
