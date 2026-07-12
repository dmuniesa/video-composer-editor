"""Bridge from Python logging to the in-app Logs tab.

Every record the app logs is persisted per-project (see logstore) and pushed
live over SSE, so you can debug AI analysis (the agy/OpenAI calls, prompts, raw
responses, parse failures) from the browser without watching the server
terminal — and the history survives an app restart.

Each record is tagged with the project it belongs to via a context var set
around background jobs (where all the AI work runs); use_project() opens that
scope. Records emitted outside any project scope (e.g. server startup/errors)
are stored unattributed and shown in every project's tab."""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os
import traceback

from . import logstore, settings
from .events import broadcaster

LOGGER_NAME = "app"

# The project a log record should be attributed to, for the duration of a job.
_current_pid: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_pid", default=None)


@contextlib.contextmanager
def use_project(pid: str):
    """Tag every log record emitted in this scope with `pid`. Wrapped around a
    job's work so its AI logs land in that project's Logs tab."""
    token = _current_pid.set(pid)
    try:
        yield
    finally:
        _current_pid.reset(token)


def current_project() -> str | None:
    return _current_pid.get()


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
    """Persists each record (tagged with its project) and streams it to the UI."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            ts = record.created
            level = record.levelname
            logger = record.name
            pid = current_project()
        except Exception:  # noqa: BLE001 - logging must never raise
            return
        try:
            seq = logstore.append(ts, level, logger, message, pid)
        except Exception:  # noqa: BLE001 - a storage hiccup must not break logging
            seq = -1
        entry = {"seq": seq, "time": ts, "level": level, "logger": logger, "message": message, "project_id": pid}
        # Attributed records go to their project's tab; unattributed (global)
        # ones fan out to every open tab, matching what recent() returns.
        if pid:
            broadcaster.publish(pid, "log", entry)
        else:
            broadcaster.publish_all("log", entry)


def records(pid: str) -> list[dict]:
    return logstore.recent(pid)


def clear(pid: str) -> None:
    logstore.clear(pid)
