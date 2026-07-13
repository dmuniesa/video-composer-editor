"""Timeline tracks & clips CRUD, delegating validation to timeline_ops."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import db as dbm
from ..events import broadcaster
from ..services import timeline_ops as ops
from .deps import resolve_project

router = APIRouter()


@router.get("/projects/{pid}/timeline")
def timeline_get(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        state = ops.timeline_state(db)
        db.commit()
        return state


@router.post("/projects/{pid}/tracks")
def track_add(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        track = ops.add_track(db)
        db.commit()
        result = {"id": track.id, "index": track.index, "name": track.name}
    broadcaster.publish(pid, "timeline", {})
    return result


@router.delete("/projects/{pid}/tracks/{tid}")
def track_remove(pid: str, tid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        try:
            ops.remove_track(db, tid)
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}


class ClipCreate(BaseModel):
    track_id: int
    video_id: int
    timeline_start: float
    source_in: float
    source_out: float
    speed: float = 1.0


@router.post("/projects/{pid}/clips")
def clip_create(pid: str, body: ClipCreate) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        try:
            clip = ops.place_clip(
                db,
                video_id=body.video_id,
                track_ref=body.track_id,
                timeline_start=body.timeline_start,
                source_in=body.source_in,
                source_out=body.source_out,
                placed_by="user",
                speed=body.speed,
            )
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        result = {"id": clip.id}
    broadcaster.publish(pid, "timeline", {})
    return result


class ClipUpdate(BaseModel):
    timeline_start: float | None = None
    track_id: int | None = None
    source_in: float | None = None
    source_out: float | None = None
    speed: float | None = None


@router.patch("/projects/{pid}/clips/{cid}")
def clip_update(pid: str, cid: int, body: ClipUpdate) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        try:
            ops.update_clip(
                db,
                clip_id=cid,
                timeline_start=body.timeline_start,
                track_ref=body.track_id,
                source_in=body.source_in,
                source_out=body.source_out,
                speed=body.speed,
            )
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}


class ClipSplit(BaseModel):
    at: float


@router.post("/projects/{pid}/clips/{cid}/split")
def clip_split(pid: str, cid: int, body: ClipSplit) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        try:
            right = ops.split_clip(db, cid, body.at)
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        result = {"id": right.id}
    broadcaster.publish(pid, "timeline", {})
    return result


@router.delete("/projects/{pid}/clips/{cid}")
def clip_delete(pid: str, cid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        try:
            ops.remove_clip(db, cid)
        except ops.TimelineError as exc:
            raise HTTPException(404, str(exc))
        db.commit()
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}
