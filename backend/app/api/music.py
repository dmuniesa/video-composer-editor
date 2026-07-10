"""Song analysis results, waveform peaks, and section editing."""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from .. import db as dbm
from ..events import broadcaster
from ..models import Song, SongSection
from ..services import gemini, jobs, pipeline
from .deps import resolve_project

router = APIRouter()


def _song_dict(song: Song) -> dict:
    return {
        "path": song.path,
        "duration": song.duration,
        "bpm": song.bpm,
        "beats": song.beats,
        "downbeats": song.downbeats,
        "status": song.status,
        "error": song.error,
        "sections": [
            {
                "id": s.id,
                "start": s.start,
                "end": s.end,
                "label": s.label,
                "source": s.source,
                "energy": s.energy,
            }
            for s in song.sections
        ],
    }


@router.get("/projects/{pid}/song")
def song_get(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        song = db.scalar(select(Song))
        if song is None:
            raise HTTPException(404, "no song set")
        return _song_dict(song)


@router.get("/projects/{pid}/song/peaks")
def song_peaks(pid: str) -> dict:
    video_dir = resolve_project(pid)
    path = dbm.cache_dir_for(video_dir) / "song_peaks.json"
    if not path.is_file():
        raise HTTPException(404, "peaks not ready")
    return json.loads(path.read_text())


@router.post("/projects/{pid}/song/reanalyze")
def song_reanalyze(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        if db.scalar(select(Song)) is None:
            raise HTTPException(404, "no song set")
    pipeline.queue_song_job(pid, video_dir)
    return {"ok": True}


@router.post("/projects/{pid}/song/label")
def song_label(pid: str) -> dict:
    """Re-run Gemini semantic labeling on existing sections."""
    video_dir = resolve_project(pid)
    if not gemini.agy_available():
        raise HTTPException(409, "Antigravity CLI (agy) not available")
    with dbm.open_session(video_dir) as db:
        song = db.scalar(select(Song))
        if song is None or song.status != "ready":
            raise HTTPException(409, "song not analyzed yet")

    def work(job):
        with dbm.open_session(video_dir) as db:
            song = db.scalar(select(Song))
            sections = [
                {"start": s.start, "end": s.end, "energy": s.energy, "cluster": 0}
                for s in song.sections
            ]
            labels = gemini.label_sections(song.duration, song.bpm or 0.0, sections)
            for section, label in zip(song.sections, labels):
                if label:
                    section.label = label
                    section.source = "ai"
            db.commit()
        broadcaster.publish(pid, "song", {})

    jobs.submit(pid, "label", "label sections", work, pool="ai")
    return {"ok": True}


class SectionEdit(BaseModel):
    label: str | None = None
    start: float | None = None
    end: float | None = None


@router.patch("/projects/{pid}/song/sections/{sid}")
def section_update(pid: str, sid: int, body: SectionEdit) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        section = db.get(SongSection, sid)
        if section is None:
            raise HTTPException(404, "section not found")
        if body.label is not None:
            section.label = body.label
            section.source = "user"
        if body.start is not None:
            section.start = body.start
        if body.end is not None:
            section.end = body.end
        db.commit()
    broadcaster.publish(pid, "song", {})
    return {"ok": True}


class SectionSplit(BaseModel):
    at: float


@router.post("/projects/{pid}/song/sections/{sid}/split")
def section_split(pid: str, sid: int, body: SectionSplit) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        section = db.get(SongSection, sid)
        if section is None:
            raise HTTPException(404, "section not found")
        if not section.start + 0.5 < body.at < section.end - 0.5:
            raise HTTPException(400, "split point outside section")
        db.add(
            SongSection(
                song_id=section.song_id,
                start=body.at,
                end=section.end,
                label="",
                source="user",
                energy=section.energy,
            )
        )
        section.end = body.at
        section.source = "user"
        db.commit()
    broadcaster.publish(pid, "song", {})
    return {"ok": True}


@router.delete("/projects/{pid}/song/sections/{sid}")
def section_merge_left(pid: str, sid: int) -> dict:
    """Deleting a section merges it into its left neighbour (or extends the
    right neighbour when it is the first section)."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        section = db.get(SongSection, sid)
        if section is None:
            raise HTTPException(404, "section not found")
        song = db.get(Song, section.song_id)
        ordered = sorted(song.sections, key=lambda s: s.start)
        idx = next(i for i, s in enumerate(ordered) if s.id == sid)
        if len(ordered) <= 1:
            raise HTTPException(400, "cannot delete the only section")
        if idx > 0:
            ordered[idx - 1].end = section.end
        else:
            ordered[idx + 1].start = section.start
        db.delete(section)
        db.commit()
    broadcaster.publish(pid, "song", {})
    return {"ok": True}
