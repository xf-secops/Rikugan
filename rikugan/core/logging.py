"""Logging to the host output window AND a crash-proof log file.

The file log at <config_dir>/rikugan/rikugan_debug.log is flushed after every
write so the last line survives even if the host crashes hard.

Structured JSON log is written to rikugan_structured.jsonl for machine parsing.
"""

from __future__ import annotations

import importlib
import json
import logging
import os
import sys
import time
import threading
import traceback
from typing import Optional

from ..constants import IDA_AVAILABLE as _IDA_AVAILABLE
from .host import get_user_config_base_dir, is_binary_ninja as _is_binary_ninja
if _IDA_AVAILABLE:
    ida_kernwin = importlib.import_module("ida_kernwin")

_BN_AVAILABLE = _is_binary_ninja()
_bn_log = None
if _BN_AVAILABLE:
    try:
        _bn_log = importlib.import_module("binaryninja.log")
    except Exception:
        pass

_logger: Optional[logging.Logger] = None

# --- Crash-proof file path ---

def _log_file_path() -> str:
    base = get_user_config_base_dir()
    d = os.path.join(base, "rikugan")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "rikugan_debug.log")


class _FlushFileHandler(logging.FileHandler):
    """FileHandler that flushes + fsync after every record."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self.stream.flush()
            os.fsync(self.stream.fileno())
        except OSError:
            pass  # fsync can fail on pipes/redirected streams — non-fatal for logging


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


class IDAHandler(logging.Handler):
    """Logging handler that writes to the host's output window."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if _IDA_AVAILABLE:
            try:
                ida_kernwin.msg(f"{msg}\n")
            except RuntimeError:
                pass  # IDA output window may be destroyed during shutdown
        elif _bn_log is not None:
            try:
                if record.levelno >= logging.ERROR:
                    _bn_log.log_error(msg)
                elif record.levelno >= logging.WARNING:
                    _bn_log.log_warn(msg)
                else:
                    _bn_log.log_info(msg)
            except Exception:
                pass
        else:
            sys.stderr.write(f"{msg}\n")


def get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger
    _logger = logging.getLogger("Rikugan")
    _logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "[Rikugan %(asctime)s.%(msecs)03d %(levelname)s %(threadName)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # IDA output handler (INFO and above to avoid spamming)
    ida_handler = IDAHandler()
    ida_handler.setLevel(logging.INFO)
    ida_handler.setFormatter(logging.Formatter("[Rikugan] %(levelname)s: %(message)s"))
    _logger.addHandler(ida_handler)

    # File handler (DEBUG — everything, flush immediately)
    try:
        path = _log_file_path()
        file_handler = _FlushFileHandler(path, mode="w", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        _logger.addHandler(file_handler)
        _logger.debug(f"=== Rikugan debug log started — {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        _logger.debug(f"Log file: {path}")
        _logger.debug(f"Python: {sys.version}")
        _logger.debug(f"Thread: {threading.current_thread().name}")
    except Exception as e:
        _logger.warning(f"Could not open debug log file: {e}")

    # Structured JSON log (JSONL format for machine parsing / analytics)
    try:
        json_path = os.path.join(os.path.dirname(_log_file_path()), "rikugan_structured.jsonl")
        json_handler = _FlushFileHandler(json_path, mode="a", encoding="utf-8")
        json_handler.setLevel(logging.INFO)
        json_handler.setFormatter(_JSONFormatter())
        _logger.addHandler(json_handler)
    except Exception:
        pass  # Non-critical — structured logging is optional

    return _logger


def log_info(msg: str) -> None:
    get_logger().info(msg)


def log_warning(msg: str) -> None:
    get_logger().warning(msg)


def log_error(msg: str) -> None:
    get_logger().error(msg)


def log_debug(msg: str) -> None:
    get_logger().debug(msg)


def log_trace(label: str) -> None:
    """Verbose trace-level log (logged at DEBUG level with TRACE prefix)."""
    get_logger().debug(f"TRACE {label}")
