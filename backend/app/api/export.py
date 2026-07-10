"""Premiere Pro project export (FCP7 XML / xmeml v5)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from sqlalchemy import select

from .. import db as dbm
from ..models import Song, Track, Video
from ..services import xmeml
from .deps import resolve_project

router = APIRouter()


@router.get("/projects/{pid}/export.xml")
def export_xml(pid: str) -> Response:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        tracks = list(db.scalars(select(Track).order_by(Track.index)))
        clips = [c for t in tracks for c in t.clips]
        if not clips:
            raise HTTPException(409, "timeline is empty — place some clips first")
        song = db.scalar(select(Song))
        used_ids = {c.video_id for c in clips}
        videos = {
            v.id: {
                "path": str(video_dir / v.rel_path),
                "fps": v.fps,
                "width": v.width,
                "height": v.height,
                "duration": v.duration,
            }
            for v in db.scalars(select(Video).where(Video.id.in_(used_ids)))
        }
        xml = xmeml.build_xmeml(
            sequence_name=f"{video_dir.name} montage",
            videos=videos,
            tracks=[
                {
                    "name": t.name,
                    "clips": [
                        {
                            "video_id": c.video_id,
                            "timeline_start": c.timeline_start,
                            "source_in": c.source_in,
                            "source_out": c.source_out,
                        }
                        for c in t.clips
                    ],
                }
                for t in tracks
            ],
            song={"path": song.path, "duration": song.duration} if song and song.duration else None,
        )
    return Response(
        content=xml,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="montage.xml"'},
    )
