"""Application settings endpoints + per-project frame re-extraction."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from .. import db as dbm, logbuffer, settings
from ..events import broadcaster
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
    logbuffer.apply_level()  # apply the verbose-logging toggle live
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


@router.post("/projects/{pid}/clear_analysis")
def project_clear_analysis(pid: str) -> dict:
    """Delete the AI-generated analysis (description, score, hashtags, raw
    response) from every video in this project. Use this when the AI produced
    wrong or mixed-up descriptions (e.g. after the agy shared-scratch bug) and
    you want them gone. Extracted frames are kept; clips go back to 'extracted'
    so analysis can be re-run manually from the Library when you're ready.
    Does NOT re-run the AI itself.
    """
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        videos = list(db.scalars(select(Video)))
        cleared = 0
        for v in videos:
            if v.status == "analyzing":
                continue  # a job is mid-flight; leave it alone
            if v.analysis is not None:
                db.delete(v.analysis)
                cleared += 1
            # Reset terminal states so the clip can be re-analyzed later.
            # pending/extracting are left alone (media not ready).
            if v.status in ("ready", "error"):
                v.status = "extracted"
                v.error = None
        db.commit()
    broadcaster.publish(pid, "videos", {})
    return {"cleared": cleared}
