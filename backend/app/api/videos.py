"""Video listing, ratings (single + batch), manual analysis edits, ranges."""
from __future__ import annotations

import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import db as dbm, settings
from ..events import broadcaster
from ..models import (
    ExcludedFile,
    Face,
    Person,
    TimelineClip,
    Video,
    VideoAnalysis,
    VideoRange,
    VideoRating,
)
from .deps import resolve_project

router = APIRouter()


def _people_of(v: Video) -> list[dict]:
    """Named, non-hidden persons appearing in this video (via its non-ignored
    faces)."""
    seen: dict[int, str] = {}
    for f in v.faces:
        if not f.ignored and f.person is not None and f.person.name and not f.person.hidden:
            seen[f.person.id] = f.person.name
    return [{"id": pid, "name": name} for pid, name in sorted(seen.items(), key=lambda i: i[1].lower())]


def video_dict(v: Video, people: list[dict] | None = None) -> dict:
    # Optional analysis aspects are gated by their Settings toggle: a disabled
    # aspect is served empty even when an old analysis stored a value, so the
    # UI stays consistent with what the AI is currently asked for.
    aspects = settings.get().analysis
    a = v.analysis
    return {
        "id": v.id,
        "rel_path": v.rel_path,
        "source_id": v.source_id,
        "source_label": (v.source.label or v.source.path) if v.source else "",
        "filename": v.filename,
        "duration": v.duration,
        "fps": v.fps,
        "width": v.width,
        "height": v.height,
        "codec": v.codec,
        "size": v.size,
        "shot_at": v.shot_at,
        "meta": v.meta,
        "status": v.status,
        "error": v.error,
        "has_proxy": v.has_proxy,
        "frame_count": v.frame_count,
        "faces_status": v.faces_status,
        "people": _people_of(v) if people is None else people,
        "description": a.description if a else "",
        "ai_score": a.ai_score if a else None,
        "hashtags": a.hashtags if a else [],
        "mood": a.mood if a and aspects.mood else [],
        "energy": a.energy if a and aspects.energy else None,
        "scene": a.scene if a and aspects.scene else None,
        "time_of_day": a.time_of_day if a and aspects.scene else None,
        "shot_type": a.shot_type if a and aspects.scene else None,
        "highlights": a.highlights if a and aspects.highlights else [],
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
        # One batch query for people-per-video instead of lazy-loading each
        # video's faces (N+1) in video_dict.
        by_video: dict[int, dict[int, str]] = {}
        rows = db.execute(
            select(Face.video_id, Person.id, Person.name)
            .join(Person, Face.person_id == Person.id)
            .where(Face.ignored.is_(False), Person.name != "", Person.hidden.is_(False))
        )
        for vid, person_id, name in rows:
            by_video.setdefault(vid, {})[person_id] = name
        return [
            video_dict(
                v,
                people=[
                    {"id": pid_, "name": name}
                    for pid_, name in sorted(
                        by_video.get(v.id, {}).items(), key=lambda i: i[1].lower()
                    )
                ],
            )
            for v in db.scalars(select(Video).order_by(Video.filename))
        ]


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


@router.delete("/projects/{pid}/videos/{vid}")
def video_delete(pid: str, vid: int) -> dict:
    """Remove a video from the project: drops its DB row (analysis, rating,
    ranges cascade), any timeline clips using it, and its cache folder. The
    source file on disk is left untouched, and an ExcludedFile tombstone is
    recorded so a later rescan of its source skips the file instead of re-adding
    it (restore it from Excluded to undo)."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, vid)
        if video is None:
            raise HTTPException(404, "video not found")
        # TimelineClip has no cascade to Video; remove clips referencing it.
        for clip in db.scalars(select(TimelineClip).where(TimelineClip.video_id == vid)):
            db.delete(clip)
        cache = dbm.cache_dir_for(video_dir) / video.cache_key
        shutil.rmtree(cache, ignore_errors=True)
        # Remember the deletion so a rescan won't resurrect the file.
        already = db.scalar(
            select(ExcludedFile).where(
                ExcludedFile.source_id == video.source_id,
                ExcludedFile.rel_path == video.rel_path,
            )
        )
        if already is None:
            db.add(
                ExcludedFile(
                    source_id=video.source_id,
                    rel_path=video.rel_path,
                    filename=video.filename,
                )
            )
        db.delete(video)
        db.commit()
    broadcaster.publish(pid, "videos", {})
    broadcaster.publish(pid, "timeline", {"source": "video-removed"})
    return {"ok": True}


@router.get("/projects/{pid}/excluded")
def excluded_list(pid: str) -> list[dict]:
    """Files the user deleted in Review that a rescan will keep skipping."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        rows = db.scalars(
            select(ExcludedFile).order_by(ExcludedFile.excluded_at.desc())
        )
        return [
            {
                "id": e.id,
                "source_id": e.source_id,
                "rel_path": e.rel_path,
                "filename": e.filename,
                "excluded_at": e.excluded_at.isoformat() if e.excluded_at else None,
            }
            for e in rows
        ]


@router.delete("/projects/{pid}/excluded/{eid}")
def excluded_restore(pid: str, eid: int) -> dict:
    """Drop a tombstone so the next scan re-adds the file. Returns the file's
    source_id/rel_path so the caller can trigger a rescan to bring it back."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        exc = db.get(ExcludedFile, eid)
        if exc is None:
            raise HTTPException(404, "excluded file not found")
        db.delete(exc)
        db.commit()
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
