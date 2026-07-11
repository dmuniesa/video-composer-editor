"""Application settings endpoints + per-project frame re-extraction."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from .. import db as dbm, settings
from ..models import Video
from ..services import ai, frames, pipeline
from .deps import resolve_project

router = APIRouter()


@router.get("/settings")
def settings_get() -> dict:
    data = settings.get().model_dump()
    data["ai_status"] = {"available": ai.available(), "provider": ai.provider()}
    return data


@router.put("/settings")
def settings_put(body: settings.Settings) -> dict:
    settings.save(body)
    return settings_get()


@router.post("/settings/test_ai")
def settings_test_ai() -> dict:
    """Send a trivial prompt through the configured provider."""
    return ai.test_connection()


@router.post("/projects/{pid}/reextract")
def project_reextract(pid: str) -> dict:
    """Delete derived frames/thumbnails/filmstrips and re-queue media jobs so
    the current frame settings take effect on every video of the project."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        videos = list(db.scalars(select(Video)))
        for v in videos:
            frames.clear_derived_frames(pipeline.video_cache(video_dir, v.cache_key))
            v.frame_count = 0
        db.commit()
    for v in videos:
        pipeline.queue_media_job(pid, video_dir, v.id)
    return {"queued": len(videos)}
