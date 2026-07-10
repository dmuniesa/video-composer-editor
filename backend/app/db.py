"""Per-project SQLite engines plus a small registry of known projects.

Each project's database lives in <video_dir>/.montage-cache/montage.db.
A JSON registry in the user's home dir maps short project ids to video dirs
so the API can address projects as /api/projects/{pid}/... across restarts.
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
            _engines[resolved] = sessionmaker(bind=engine, expire_on_commit=False)
        return _engines[resolved]


def open_session(video_dir: str | Path) -> Session:
    return session_factory(video_dir)()
