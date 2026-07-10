"""Shared FastAPI dependencies."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from .. import db as dbm


def resolve_project(pid: str) -> Path:
    video_dir = dbm.video_dir_for(pid)
    if video_dir is None or not video_dir.is_dir():
        raise HTTPException(404, f"unknown project {pid}")
    return video_dir
