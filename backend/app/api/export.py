"""Timeline export: Premiere Pro / DaVinci Resolve (FCP7 XML / xmeml v5)
and Final Cut Pro X (FCPXML 1.9)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from .. import db as dbm
from ..models import Project, Song, Track, Video
from ..services import fcpxml, xmeml
from .deps import resolve_project

router = APIRouter()


def _gather(pid: str) -> dict:
    """Collect everything the XML builders need from the project DB."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        tracks = list(db.scalars(select(Track).order_by(Track.index)))
        clips = [c for t in tracks for c in t.clips]
        if not clips:
            raise HTTPException(409, "timeline is empty — place some clips first")
        song = db.scalar(select(Song))
        project = db.scalar(select(Project))
        used_ids = {c.video_id for c in clips}
        return {
            "sequence_name": f"{video_dir.name} montage",
            "sequence_fps": (project.composition_fps if project else None) or 25.0,
            "sequence_width": (project.composition_width if project else None) or 0,
            "sequence_height": (project.composition_height if project else None) or 0,
            "videos": {
                v.id: {
                    "path": str((Path(v.source.path) if v.source else video_dir) / v.rel_path),
                    "fps": v.fps,
                    "width": v.width,
                    "height": v.height,
                    "duration": v.duration,
                }
                for v in db.scalars(select(Video).where(Video.id.in_(used_ids)))
            },
            "tracks": [
                {
                    "name": t.name,
                    "audio_muted": t.audio_muted,
                    "audio_volume": t.audio_volume,
                    "clips": [
                        {
                            "video_id": c.video_id,
                            "timeline_start": c.timeline_start,
                            "source_in": c.source_in,
                            "source_out": c.source_out,
                            "speed": c.speed or 1.0,
                        }
                        for c in t.clips
                    ],
                }
                for t in tracks
            ],
            "song": {
                "path": song.path,
                "duration": song.duration,
                "muted": song.muted,
                "volume": song.volume,
            }
            if song and song.duration
            else None,
        }


def _attachment(content: str, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/projects/{pid}/export.xml")
def export_premiere(pid: str) -> Response:
    data = _gather(pid)
    return _attachment(xmeml.build_xmeml(**data), "montage.xml")


@router.get("/projects/{pid}/export-resolve.xml")
def export_resolve(pid: str) -> Response:
    # DaVinci Resolve imports FCP7 XML natively (File > Import > Timeline),
    # so it gets the same xmeml document under a distinct name.
    data = _gather(pid)
    return _attachment(xmeml.build_xmeml(**data), "montage-resolve.xml")


@router.get("/projects/{pid}/export.fcpxml")
def export_fcpx(pid: str) -> Response:
    data = _gather(pid)
    return _attachment(fcpxml.build_fcpxml(**data), "montage.fcpxml")
