"""Per-project SQLite engines plus a small registry of known projects.

Each project's database lives in <project_dir>/.montage-cache/montage.db, where
<project_dir> is the storage folder the user chose (decoupled from the footage).
A JSON registry in the user's home dir maps short project ids to those storage
dirs so the API can address projects as /api/projects/{pid}/... across restarts.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base

CACHE_DIR_NAME = ".montage-cache"
REGISTRY_PATH = Path(
    os.environ.get("MONTAGE_REGISTRY", str(Path.home() / ".video-montage-composer" / "projects.json"))
)

_engines: dict[str, sessionmaker] = {}
_lock = threading.Lock()


def project_id_for(video_dir: str | Path) -> str:
    resolved = str(Path(video_dir).resolve())
    return hashlib.sha1(resolved.encode()).hexdigest()[:12]


def cache_dir_for(video_dir: str | Path) -> Path:
    return Path(video_dir).resolve() / CACHE_DIR_NAME


def _load_registry() -> dict[str, str]:
    try:
        return json.loads(REGISTRY_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_registry(reg: dict[str, str]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(reg, indent=2))


def register_project(video_dir: str | Path) -> str:
    pid = project_id_for(video_dir)
    with _lock:
        reg = _load_registry()
        reg[pid] = str(Path(video_dir).resolve())
        _save_registry(reg)
    return pid


def list_projects() -> dict[str, str]:
    return _load_registry()


def video_dir_for(pid: str) -> Path | None:
    path = _load_registry().get(pid)
    return Path(path) if path else None


def _ensure_columns(engine) -> None:
    """create_all only adds new tables, never columns; add any columns missing
    from existing tables so old project databases keep working."""
    with engine.begin() as conn:
        for table in Base.metadata.tables.values():
            existing = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info('{table.name}')")}
            if not existing:
                continue
            for col in table.columns:
                if col.name in existing:
                    continue
                spec = f'"{col.name}" {col.type.compile(engine.dialect)}'
                default = getattr(col.default, "arg", None)
                if default is not None and not callable(default):
                    spec += f" DEFAULT '{default}'" if isinstance(default, str) else f" DEFAULT {default}"
                conn.exec_driver_sql(f'ALTER TABLE "{table.name}" ADD COLUMN {spec}')


def _seed_sources(engine) -> None:
    """Back-fill a Source for legacy databases. A pre-multi-source project has
    videos with source_id IS NULL; give them a single source pointing at the
    project's original folder (project.video_dir) so everything keeps resolving.
    New projects start with zero videos, so nothing is seeded for them."""
    from datetime import datetime, timezone

    with engine.begin() as conn:
        orphan = conn.exec_driver_sql(
            "SELECT COUNT(*) FROM video WHERE source_id IS NULL"
        ).scalar()
        if not orphan:
            return
        row = conn.exec_driver_sql("SELECT video_dir FROM project LIMIT 1").fetchone()
        if row is None or not row[0]:
            return
        path = str(Path(row[0]).resolve())
        label = Path(path).name
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
        conn.exec_driver_sql(
            "INSERT INTO source (path, label, added_at) VALUES (?, ?, ?)",
            (path, label, now),
        )
        sid = conn.exec_driver_sql("SELECT last_insert_rowid()").scalar()
        conn.exec_driver_sql(
            "UPDATE video SET source_id = ? WHERE source_id IS NULL", (sid,)
        )


def session_factory(video_dir: str | Path) -> sessionmaker:
    resolved = str(Path(video_dir).resolve())
    with _lock:
        if resolved not in _engines:
            cache = cache_dir_for(resolved)
            cache.mkdir(parents=True, exist_ok=True)
            engine = create_engine(
                f"sqlite:///{cache / 'montage.db'}",
                connect_args={"check_same_thread": False, "timeout": 30},
            )
            Base.metadata.create_all(engine)
            _ensure_columns(engine)
            _seed_sources(engine)
            _engines[resolved] = sessionmaker(bind=engine, expire_on_commit=False)
        return _engines[resolved]


def open_session(video_dir: str | Path) -> Session:
    return session_factory(video_dir)()
