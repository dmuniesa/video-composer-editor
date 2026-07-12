"""Persistent, per-project store for the app's log records.

A single SQLite database for the whole program (next to the project registry,
i.e. ~/.video-montage-composer/logs.db), with one `log_entry` table keyed by
project id. This is what makes the Logs tab survive an app restart: each log
line the backend emits is written here and tagged with the project it belongs
to, so every project keeps its own history.

Kept deliberately separate from the per-project montage.db files: log lines are
tied to a *run* (which project's analysis was executing), not to the footage,
and we don't want a log write to ever contend with a project's real data."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from . import db as dbm

# Total rows kept across all projects; older lines are pruned. Generous because
# a verbose (debug) AI run dumps full prompts and raw responses.
RETENTION = 20_000
_PRUNE_EVERY = 500

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_conn_path: str | None = None
_since_prune = 0


def _db_path() -> Path:
    """Beside the project registry (honours MONTAGE_REGISTRY, and the test
    fixture that repoints it), or MONTAGE_LOG_DB when set explicitly."""
    override = os.environ.get("MONTAGE_LOG_DB")
    if override:
        return Path(override)
    return dbm.REGISTRY_PATH.parent / "logs.db"


def _connect() -> sqlite3.Connection:
    """Open (once) the shared connection, reconnecting if the target path
    changed — the latter keeps tests isolated when the registry is repointed."""
    global _conn, _conn_path
    path = str(_db_path().resolve())
    if _conn is not None and _conn_path == path:
        return _conn
    if _conn is not None:
        _conn.close()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS log_entry (
               seq        INTEGER PRIMARY KEY AUTOINCREMENT,
               ts         REAL NOT NULL,
               level      TEXT NOT NULL,
               logger     TEXT NOT NULL,
               message    TEXT NOT NULL,
               project_id TEXT
           )"""
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_log_project ON log_entry(project_id, seq)")
    conn.commit()
    _conn, _conn_path = conn, path
    return conn


def append(ts: float, level: str, logger: str, message: str, project_id: str | None) -> int:
    """Persist one log line and return its assigned (monotonic) seq. seq comes
    from the DB so it stays unique across restarts — the UI uses it as a key."""
    global _since_prune
    with _lock:
        conn = _connect()
        cur = conn.execute(
            "INSERT INTO log_entry (ts, level, logger, message, project_id) VALUES (?, ?, ?, ?, ?)",
            (ts, level, logger, message, project_id),
        )
        seq = int(cur.lastrowid)
        _since_prune += 1
        if _since_prune >= _PRUNE_EVERY:
            _since_prune = 0
            conn.execute(
                "DELETE FROM log_entry WHERE seq <= (SELECT MAX(seq) FROM log_entry) - ?",
                (RETENTION,),
            )
        conn.commit()
        return seq


def recent(project_id: str, limit: int = 2000) -> list[dict]:
    """This project's most recent log lines, oldest-first for the UI. Includes
    unattributed (global) lines — server startup/errors — so they surface in
    every project's tab."""
    with _lock:
        conn = _connect()
        rows = conn.execute(
            """SELECT seq, ts, level, logger, message, project_id
                 FROM log_entry
                WHERE project_id = ? OR project_id IS NULL
                ORDER BY seq DESC
                LIMIT ?""",
            (project_id, limit),
        ).fetchall()
    rows.reverse()
    return [
        {"seq": r[0], "time": r[1], "level": r[2], "logger": r[3], "message": r[4], "project_id": r[5]}
        for r in rows
    ]


def clear(project_id: str) -> None:
    """Clear what this project's tab shows: its own lines plus the shared global
    ones (so the view actually empties). Other projects' own lines are kept."""
    with _lock:
        conn = _connect()
        conn.execute(
            "DELETE FROM log_entry WHERE project_id = ? OR project_id IS NULL", (project_id,)
        )
        conn.commit()
