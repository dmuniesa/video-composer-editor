"""Video listing, ratings (single + batch), manual analysis edits, ranges."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import db as dbm
from ..events import broadcaster
from ..models import Video, VideoAnalysis, VideoRange, VideoRating
from .deps import resolve_project

router = APIRouter()


def video_dict(v: Video) -> dict:
    return {
        "id": v.id,
        "rel_path": v.rel_path,
        "filename": v.filename,
        "duration": v.duration,
        "fps": v.fps,
        "width": v.width,
        "height": v.height,
        "codec": v.codec,
        "size": v.size,
        "shot_at": v.shot_at,
        "status": v.status,
        "error": v.error,
        "has_proxy": v.has_proxy,
        "frame_count": v.frame_count,
        "description": v.analysis.description if v.analysis else "",
        "ai_score": v.analysis.ai_score if v.analysis else None,
        "hashtags": v.analysis.hashtags if v.analysis else [],
        "stars": v.rating.stars if v.rating else 0,
        "rejected": v.rating.rejected if v.rating else False,
        "ranges": [
            {"id": r.id, "t_in": r.t_in, "t_out": r.t_out, "label": r.label}
            for r in v.ranges
        ],
    }


@router.get("/projects/{pid}/videos")
def videos_list(pid: str) -> list[dict]:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        return [video_dict(v) for v in db.scalars(select(Video).order_by(Video.filename))]


class RatingRequest(BaseModel):
    video_ids: list[int]
    stars: int | None = None
    rejected: bool | None = None


@router.post("/projects/{pid}/videos/rating")
def videos_rate(pid: str, body: RatingRequest) -> dict:
    """Batch rating: applies stars and/or rejected to all given videos."""
    video_dir = resolve_project(pid)
    if body.stars is not None and not 0 <= body.stars <= 5:
        raise HTTPException(400, "stars must be 0-5")
    with dbm.open_session(video_dir) as db:
        for vid in body.video_ids:
            video = db.get(Video, vid)
            if video is None:
                continue
            rating = video.rating or VideoRating(video_id=vid)
            if body.stars is not None:
                rating.stars = body.stars
            if body.rejected is not None:
                rating.rejected = body.rejected
            db.add(rating)
        db.commit()
    broadcaster.publish(pid, "videos", {})
    return {"ok": True}


class AnalysisEdit(BaseModel):
    description: str | None = None
    hashtags: list[str] | None = None


@router.patch("/projects/{pid}/videos/{vid}/analysis")
def video_edit_analysis(pid: str, vid: int, body: AnalysisEdit) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, vid)
        if video is None:
            raise HTTPException(404, "video not found")
        analysis = video.analysis or VideoAnalysis(video_id=vid)
        if body.description is not None:
            analysis.description = body.description
        if body.hashtags is not None:
            analysis.hashtags = [h.strip().lower().lstrip("#") for h in body.hashtags if h.strip()]
        db.add(analysis)
        db.commit()
        result = video_dict(video)
    broadcaster.publish(pid, "video", {"id": vid})
    return result


class RangeRequest(BaseModel):
    t_in: float
    t_out: float
    label: str = ""


@router.post("/projects/{pid}/videos/{vid}/ranges")
def range_create(pid: str, vid: int, body: RangeRequest) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, vid)
        if video is None:
            raise HTTPException(404, "video not found")
        if body.t_out - body.t_in < 0.1:
            raise HTTPException(400, "range too short")
        r = VideoRange(
            video_id=vid,
            t_in=max(0.0, body.t_in),
            t_out=min(body.t_out, video.duration or body.t_out),
            label=body.label,
        )
        db.add(r)
        db.commit()
        result = {"id": r.id, "t_in": r.t_in, "t_out": r.t_out, "label": r.label}
    broadcaster.publish(pid, "video", {"id": vid})
    return result


@router.patch("/projects/{pid}/videos/{vid}/ranges/{rid}")
def range_update(pid: str, vid: int, rid: int, body: RangeRequest) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        r = db.get(VideoRange, rid)
        if r is None or r.video_id != vid:
            raise HTTPException(404, "range not found")
        if body.t_out - body.t_in < 0.1:
            raise HTTPException(400, "range too short")
        r.t_in, r.t_out, r.label = body.t_in, body.t_out, body.label
        db.commit()
        result = {"id": r.id, "t_in": r.t_in, "t_out": r.t_out, "label": r.label}
    broadcaster.publish(pid, "video", {"id": vid})
    return result


@router.delete("/projects/{pid}/videos/{vid}/ranges/{rid}")
def range_delete(pid: str, vid: int, rid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        r = db.get(VideoRange, rid)
        if r is None or r.video_id != vid:
            raise HTTPException(404, "range not found")
        db.delete(r)
        db.commit()
    broadcaster.publish(pid, "video", {"id": vid})
    return {"ok": True}
