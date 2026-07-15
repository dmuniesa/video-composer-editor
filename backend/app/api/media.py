"""Media serving: original videos / proxies with HTTP Range support (needed
for scrubbing in <video>), plus thumbnails, filmstrips, frames and the song."""
from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from .. import db as dbm
from ..models import Face, Song, Video
from .deps import resolve_project

router = APIRouter()

CHUNK = 1024 * 512
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _ranged(request: Request, path: Path) -> Response:
    if not path.is_file():
        raise HTTPException(404, "media file missing")
    size = path.stat().st_size
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    range_header = request.headers.get("range")

    start, end = 0, size - 1
    status = 200
    if range_header:
        m = RANGE_RE.match(range_header)
        if m:
            if m.group(1):
                start = int(m.group(1))
            if m.group(2):
                end = min(int(m.group(2)), size - 1)
            elif m.group(1) == "" and m.group(2):
                start = max(0, size - int(m.group(2)))
            if start > end or start >= size:
                raise HTTPException(416, "invalid range")
            status = 206

    def iterator():
        with path.open("rb") as f:
            f.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = f.read(min(CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                yield chunk

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
    }
    if status == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(iterator(), status_code=status, media_type=content_type, headers=headers)


def _get_video(pid: str, vid: int) -> tuple[Path, Video, Path]:
    """Returns (project_dir, video, original_file_path). The original path is
    resolved from the video's source inside the session, since the source is
    lazy-loaded and the row is detached once the session closes."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, vid)
        if video is None:
            raise HTTPException(404, "video not found")
        orig = (Path(video.source.path) if video.source else video_dir) / video.rel_path
    return video_dir, video, orig


@router.get("/media/{pid}/video/{vid}")
def media_video(pid: str, vid: int, request: Request) -> Response:
    video_dir, video, orig = _get_video(pid, vid)
    if video.has_proxy:
        path = dbm.cache_dir_for(video_dir) / video.cache_key / "proxy.mp4"
    else:
        path = orig
    return _ranged(request, path)


@router.get("/media/{pid}/preview/{vid}")
def media_preview(pid: str, vid: int, request: Request) -> Response:
    """Low-res preview proxy; falls back to the normal playback file while the
    preview hasn't been generated yet (older scans, job still running)."""
    video_dir, video, orig = _get_video(pid, vid)
    path = dbm.cache_dir_for(video_dir) / video.cache_key / "preview.mp4"
    if not path.is_file():
        if video.has_proxy:
            path = dbm.cache_dir_for(video_dir) / video.cache_key / "proxy.mp4"
        else:
            path = orig
    return _ranged(request, path)


@router.get("/media/{pid}/thumb/{vid}")
def media_thumb(pid: str, vid: int) -> FileResponse:
    video_dir, video, _orig = _get_video(pid, vid)
    path = dbm.cache_dir_for(video_dir) / video.cache_key / "thumb.jpg"
    if not path.is_file():
        raise HTTPException(404, "thumbnail not ready")
    return FileResponse(path)


@router.get("/media/{pid}/filmstrip/{vid}")
def media_filmstrip(pid: str, vid: int) -> FileResponse:
    video_dir, video, _orig = _get_video(pid, vid)
    path = dbm.cache_dir_for(video_dir) / video.cache_key / "filmstrip.jpg"
    if not path.is_file():
        raise HTTPException(404, "filmstrip not ready")
    return FileResponse(path)


@router.get("/media/{pid}/frame/{vid}/{n}")
def media_frame(pid: str, vid: int, n: int) -> FileResponse:
    video_dir, video, _orig = _get_video(pid, vid)
    path = dbm.cache_dir_for(video_dir) / video.cache_key / f"frame_{n:02d}.jpg"
    if not path.is_file():
        raise HTTPException(404, "frame not found")
    return FileResponse(path)


@router.get("/media/{pid}/face/{fid}")
def media_face(pid: str, fid: int) -> FileResponse:
    """Cropped face thumbnail saved at detection time by services/faces.py."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        face = db.get(Face, fid)
        if face is None:
            raise HTTPException(404, "face not found")
        cache_key = face.video.cache_key
    path = dbm.cache_dir_for(video_dir) / cache_key / "faces" / f"crop_{fid}.jpg"
    if not path.is_file():
        raise HTTPException(404, "face crop missing")
    return FileResponse(path)


@router.get("/media/{pid}/face/{fid}/frame")
def media_face_frame(pid: str, fid: int) -> FileResponse:
    """Full sampled frame the face was detected in (the face viewer overlays
    the bbox on it client-side)."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        face = db.get(Face, fid)
        if face is None:
            raise HTTPException(404, "face not found")
        cache_key = face.video.cache_key
        frame_index = face.frame_index
    path = dbm.cache_dir_for(video_dir) / cache_key / "faces" / f"src_{frame_index:03d}.jpg"
    if not path.is_file():
        raise HTTPException(404, "source frame missing (re-run detection)")
    return FileResponse(path)


@router.get("/media/{pid}/song")
def media_song(pid: str, request: Request) -> Response:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        from sqlalchemy import select

        song = db.scalar(select(Song))
    if song is None:
        raise HTTPException(404, "no song set")
    return _ranged(request, Path(song.path))
