"""Timeline tracks & clips CRUD, delegating validation to timeline_ops."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import db as dbm
from ..events import broadcaster
from ..services import audio_loudness
from ..services import timeline_history as history
from ..services import timeline_ops as ops
from .deps import resolve_project

router = APIRouter()

# Pids with a loudness-normalisation run in flight, to reject concurrent calls.
_NORMALIZE_IN_FLIGHT: set[str] = set()


@router.get("/projects/{pid}/timeline")
def timeline_get(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        state = ops.timeline_state(db)
        db.commit()
        state["can_undo"] = history.can_undo(pid)
        state["can_redo"] = history.can_redo(pid)
        return state


@router.post("/projects/{pid}/tracks")
def track_add(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        snap = history.snapshot(db)
        track = ops.add_track(db)
        db.commit()
        history.record(pid, snap)
        result = {"id": track.id, "index": track.index, "name": track.name}
    broadcaster.publish(pid, "timeline", {})
    return result


@router.delete("/projects/{pid}/tracks/{tid}")
def track_remove(pid: str, tid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        snap = history.snapshot(db)
        try:
            ops.remove_track(db, tid)
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        history.record(pid, snap)
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}


class TrackAudioUpdate(BaseModel):
    muted: bool | None = None
    volume: float | None = None


@router.patch("/projects/{pid}/tracks/{tid}/audio")
def track_audio_update(pid: str, tid: int, body: TrackAudioUpdate) -> dict:
    """Mute / volume for a track's clip-audio lane. Not a structural edit, so it
    stays out of the undo history."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        track = db.get(ops.Track, tid)
        if track is None:
            raise HTTPException(404, "track not found")
        if body.muted is not None:
            track.audio_muted = body.muted
        if body.volume is not None:
            track.audio_volume = max(0.0, min(4.0, body.volume))  # up to ~+12 dB
        db.commit()
        result = {
            "id": track.id,
            "audio_muted": track.audio_muted,
            "audio_volume": track.audio_volume,
        }
    broadcaster.publish(pid, "timeline", {"source": "track-audio"})
    return result


class ClipAudioUpdate(BaseModel):
    audio_gain_db: float


@router.patch("/projects/{pid}/clips/{cid}/audio")
def clip_audio_update(pid: str, cid: int, body: ClipAudioUpdate) -> dict:
    """Per-clip audio gain offset (dB), set from the clip's right-click menu.
    A mix parameter (like track volume), so it stays out of the undo history."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        clip = db.get(ops.TimelineClip, cid)
        if clip is None:
            raise HTTPException(404, "clip not found")
        clip.audio_gain_db = max(-24.0, min(24.0, float(body.audio_gain_db)))
        db.commit()
        result = {"id": clip.id, "audio_gain_db": clip.audio_gain_db}
    broadcaster.publish(pid, "timeline", {"source": "clip-audio"})
    return result


class NormalizeAudioRequest(BaseModel):
    enabled: bool
    target_lufs: float = -16.0


@router.post("/projects/{pid}/normalize-audio")
def normalize_audio(pid: str, body: NormalizeAudioRequest) -> dict:
    """Toggle EBU R128 loudness normalisation across all clips.

    When enabling, measures each clip's integrated LUFS (ffmpeg loudnorm) and
    stores a per-clip ``norm_gain_db = target - measured`` so every clip lands at
    ``target_lufs``. Runs synchronously (one ffmpeg decode per clip). Bulk and
    slow, so like other mix parameters it bypasses the undo history. Only the
    clips' audio is normalised — the background song is left untouched."""
    if pid in _NORMALIZE_IN_FLIGHT:
        raise HTTPException(409, "normalization already running")
    video_dir = resolve_project(pid)
    _NORMALIZE_IN_FLIGHT.add(pid)
    try:
        with dbm.open_session(video_dir) as db:
            project = db.scalar(select(ops.Project))
            if project is None:
                raise HTTPException(404, "project not found")
            project.normalize_audio = body.enabled
            project.normalize_target_lufs = body.target_lufs
            report: list[dict] = []
            if body.enabled:
                report = audio_loudness.normalize_project(db, video_dir, body.target_lufs)
            db.commit()
    finally:
        _NORMALIZE_IN_FLIGHT.discard(pid)
    broadcaster.publish(pid, "timeline", {"source": "normalize"})
    return {"enabled": body.enabled, "target_lufs": body.target_lufs, "report": report}


@router.post("/projects/{pid}/timeline/undo")
def timeline_undo(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        target = history.peek(pid, "undo")
        if target is None:
            raise HTTPException(409, "nothing to undo")
        current = history.snapshot(db)
        history.restore(db, target)
        db.commit()
        history.commit_undo(pid, current)
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}


@router.post("/projects/{pid}/timeline/redo")
def timeline_redo(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        target = history.peek(pid, "redo")
        if target is None:
            raise HTTPException(409, "nothing to redo")
        current = history.snapshot(db)
        history.restore(db, target)
        db.commit()
        history.commit_redo(pid, current)
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
        snap = history.snapshot(db)
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
        history.record(pid, snap)
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
        snap = history.snapshot(db)
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
        history.record(pid, snap)
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}


class ClipSplit(BaseModel):
    at: float


@router.post("/projects/{pid}/clips/{cid}/split")
def clip_split(pid: str, cid: int, body: ClipSplit) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        snap = history.snapshot(db)
        try:
            right = ops.split_clip(db, cid, body.at)
        except ops.TimelineError as exc:
            raise HTTPException(400, str(exc))
        db.commit()
        history.record(pid, snap)
        result = {"id": right.id}
    broadcaster.publish(pid, "timeline", {})
    return result


@router.delete("/projects/{pid}/clips/{cid}")
def clip_delete(pid: str, cid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        snap = history.snapshot(db)
        try:
            ops.remove_clip(db, cid)
        except ops.TimelineError as exc:
            raise HTTPException(404, str(exc))
        db.commit()
        history.record(pid, snap)
    broadcaster.publish(pid, "timeline", {})
    return {"ok": True}
