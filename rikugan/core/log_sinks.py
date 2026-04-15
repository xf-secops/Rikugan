"""Logging sink implementations: host output, crash-safe file, and structured JSONL.

Each sink is a self-contained ``logging.Handler`` subclass. The bootstrap
module (``logging.py``) wires them into the Rikugan logger — importers
never need to depend on individual sinks.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from collections.abc import Callable

from .host import get_user_config_base_dir

# ---------------------------------------------------------------------------
# Host sink registration
# ---------------------------------------------------------------------------

# Callable[[str, int], None] — receives (formatted_message, levelno)
_host_sink: Callable[[str, int], None] | None = None


def register_host_sink(sink: Callable[[str, int], None]) -> None:
    """Register a host-specific log sink (called from host entry points)."""
    global _host_sink
    _host_sink = sink


def _resolve_host_sink() -> Callable[[str, int], None] | None:
    """Auto-detect and register host sink on first use."""
    global _host_sink
    if _host_sink is not None:
        return _host_sink

    try:
        from .host import BINARY_NINJA_AVAILABLE, IDA_AVAILABLE
    except Exception:
        return None

    if IDA_AVAILABLE:
        try:
            import importlib

            ida_kernwin = importlib.import_module("ida_kernwin")

            def _ida_sink(msg: str, levelno: int) -> None:
                try:
                    ida_kernwin.msg(f"{msg}\n")
                except RuntimeError as e:
                    sys.stderr.write(f"[Rikugan] IDA output window unavailable: {e}\n")

            _host_sink = _ida_sink
            return _host_sink
        except ImportError as exc:
            sys.stderr.write(f"[Rikugan] ida_kernwin import failed: {exc}\n")

    if BINARY_NINJA_AVAILABLE:
        try:
            import importlib

            _bn_log = importlib.import_module("binaryninja.log")

            def _bn_sink(msg: str, levelno: int) -> None:
                try:
                    if levelno >= logging.ERROR:
                        _bn_log.log_error(msg)
                    elif levelno >= logging.WARNING:
                        _bn_log.log_warn(msg)
                    else:
                        _bn_log.log_info(msg)
                except Exception as e:
                    sys.stderr.write(f"[Rikugan] binaryninja log emit failed: {e}\n")

            _host_sink = _bn_sink
            return _host_sink
        except ImportError as exc:
            sys.stderr.write(f"[Rikugan] binaryninja.log import failed: {exc}\n")

    return None


# ---------------------------------------------------------------------------
# Host output handler
# ---------------------------------------------------------------------------


class HostOutputHandler(logging.Handler):
    """Logging handler that delegates to the registered host sink."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        sink = _host_sink or _resolve_host_sink()
        if sink is not None:
            sink(msg, record.levelno)
        else:
            sys.stderr.write(f"{msg}\n")


# Keep old name as alias for backwards compatibility
IDAHandler = HostOutputHandler


# ---------------------------------------------------------------------------
# Crash-safe file handler
# ---------------------------------------------------------------------------


def _log_file_path() -> str:
    base = get_user_config_base_dir()
    if os.name == "nt" and os.path.isabs(base) and not os.path.splitdrive(base)[0]:
        base = os.path.join(tempfile.gettempdir(), base.lstrip("/\\").replace("/", os.sep))
    d = os.path.join(base, "rikugan")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "rikugan_debug.log")


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes after every record for crash safety."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        stream = self.stream
        try:
            if stream is not None:
                stream.flush()
        except OSError as exc:
            sys.stderr.write(f"[Rikugan] log flush failed: {exc}\n")


# ---------------------------------------------------------------------------
# Structured JSON handler
# ---------------------------------------------------------------------------


class _JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for machine parsing."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": record.created,
            "level": record.levelname,
            "thread": record.threadName,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)
