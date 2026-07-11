"""In-memory ring buffer of the app's recent log records.

Exposed to the UI (the Logs tab) and pushed live over SSE, so you can debug
AI analysis (the agy/OpenAI calls, prompts, raw responses, parse failures)
from the browser without watching the server terminal. Bounded so it never
grows without limit."""
from __future__ import annotations

import itertools
import logging
import os
import threading
import traceback
from collections import deque

from . import settings
from .events import broadcaster

LOGGER_NAME = "app"
_MAX = 1000
_records: deque[dict] = deque(maxlen=_MAX)
_lock = threading.Lock()
_seq = itertools.count(1)


def effective_level() -> str:
    """Env var wins (so ops can force a level); otherwise the Settings toggle."""
    env = os.environ.get("MONTAGE_LOG_LEVEL")
    if env:
        return env.upper()
    return "DEBUG" if settings.get().debug_logging else "INFO"


def apply_level() -> None:
    """(Re)apply the effective level to the app logger. Called at startup and
    whenever settings are saved, so the Logs-tab toggle takes effect live."""
    logging.getLogger(LOGGER_NAME).setLevel(effective_level())


class BufferHandler(logging.Handler):
    """Keeps records in memory and streams each one to the UI over SSE."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            entry = {
                "seq": next(_seq),
                "time": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": message,
            }
        except Exception:  # noqa: BLE001 - logging must never raise
            return
        with _lock:
            _records.append(entry)
        broadcaster.publish_all("log", entry)


def records() -> list[dict]:
    with _lock:
        return list(_records)


def clear() -> None:
    with _lock:
        _records.clear()
