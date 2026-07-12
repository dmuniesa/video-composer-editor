"""Project lifecycle + server-side filesystem browser + jobs + SSE."""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import db as dbm
from .. import logbuffer
from ..events import broadcaster, sse_format
from ..models import Project, Song, Video
from ..services import ai, composer, jobs, pipeline
from .deps import resolve_project

router = APIRouter()

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff"}


@router.get("/fs/list")
def fs_list(path: str = "") -> dict:
    """Server-side browser so the UI can pick real filesystem paths."""
    base = Path(path).expanduser() if path else Path.home()
    if not base.is_dir():
        raise HTTPException(400, f"not a directory: {base}")
    base = base.resolve()
    dirs, videos, audios = [], [], []
    try:
        for p in sorted(base.iterdir(), key=lambda p: p.name.lower()):
            if p.name.startswith("."):
                continue
            if p.is_dir():
                dirs.append(p.name)
            elif p.suffix.lower() in {".mp4", ".mov", ".m4v", ".avi", ".mts", ".m2ts", ".3gp", ".mkv", ".webm", ".wmv"}:
                videos.append(p.name)
            elif p.suffix.lower() in AUDIO_EXTENSIONS:
                audios.append(p.name)
    except PermissionError:
        raise HTTPException(403, f"permission denied: {base}")
    return {
        "path": str(base),
        "parent": str(base.parent) if base.parent != base else None,
        "dirs": dirs,
        "videos": videos,
        "audios": audios,
    }


class CreateProject(BaseModel):
    video_dir: str
    name: str = ""


@router.get("/projects")
def projects_list() -> list[dict]:
    out = []
    for pid, video_dir in dbm.list_projects().items():
        if Path(video_dir).is_dir():
            out.append({"id": pid, "video_dir": video_dir, "name": Path(video_dir).name})
    return out


@router.post("/projects")
def project_create(body: CreateProject) -> dict:
    video_dir = Path(body.video_dir).expanduser()
    if not video_dir.is_dir():
        raise HTTPException(400, f"not a directory: {video_dir}")
    pid = dbm.register_project(video_dir)
    with dbm.open_session(video_dir) as db:
        project = db.scalar(select(Project))
        if project is None:
            project = Project(
                name=body.name or video_dir.name, video_dir=str(video_dir.resolve())
            )
            db.add(project)
            db.commit()
    return project_get(pid)


@router.get("/projects/{pid}")
def project_get(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        project = db.scalar(select(Project))
        song = db.scalar(select(Song))
        total = db.scalar(select(func.count(Video.id))) or 0
        by_status: dict[str, int] = {}
        for status, count in db.execute(
            select(Video.status, func.count(Video.id)).group_by(Video.status)
        ):
            by_status[status] = count
        return {
            "id": pid,
            "name": project.name if project else video_dir.name,
            "video_dir": str(video_dir),
            "song_path": song.path if song else None,
            "song_status": song.status if song else None,
            "video_count": total,
            "videos_by_status": by_status,
            "ai_available": ai.available(),
            "ai_provider": ai.provider(),
            "composer_provider": composer.provider(),
            "composer_available": composer.available(),
        }


@router.post("/projects/{pid}/scan")
def project_scan(pid: str) -> dict:
    video_dir = resolve_project(pid)
    return pipeline.scan_project(pid, video_dir)


class AnalyzeRequest(BaseModel):
    video_ids: list[int] | None = None
    force: bool = False


@router.post("/projects/{pid}/analyze")
def project_analyze(pid: str, body: AnalyzeRequest) -> dict:
    video_dir = resolve_project(pid)
    if not ai.available():
        raise HTTPException(409, ai.unavailable_reason())
    with dbm.open_session(video_dir) as db:
        if body.video_ids is not None:
            ids = body.video_ids
        else:
            ids = [v.id for v in db.scalars(select(Video))]
    queued = sum(
        1 for vid in ids if pipeline.queue_analysis_job(pid, video_dir, vid, force=body.force)
    )
    return {"queued": queued}


class ComposeRequest(BaseModel):
    instructions: str = ""


@router.post("/projects/{pid}/compose")
def project_compose(pid: str, body: ComposeRequest) -> dict:
    """Auto-compose the timeline with the configured composer provider
    (agy/OpenAI one-shot prompt). Claude via MCP composes externally and
    never goes through here."""
    video_dir = resolve_project(pid)
    if not composer.available():
        raise HTTPException(409, composer.unavailable_reason())
    if jobs.has_active(pid, "compose"):
        raise HTTPException(409, "a compose job is already running")

    def work(job: jobs.Job) -> None:
        try:
            result = composer.run_compose(pid, video_dir, body.instructions, job)
            broadcaster.publish(pid, "compose", {"status": "done", **result})
        except Exception as exc:
            broadcaster.publish(pid, "compose", {"status": "error", "error": str(exc)})
            raise
        finally:
            broadcaster.publish(pid, "timeline", {"source": "compose"})

    job = jobs.submit(pid, "compose", "auto-compose", work, pool="ai")
    return {"job_id": job.id}


class SongRequest(BaseModel):
    path: str


@router.post("/projects/{pid}/song")
def project_set_song(pid: str, body: SongRequest) -> dict:
    video_dir = resolve_project(pid)
    song_path = Path(body.path).expanduser()
    if not song_path.is_file():
        raise HTTPException(400, f"not a file: {song_path}")
    if song_path.suffix.lower() not in AUDIO_EXTENSIONS:
        raise HTTPException(400, f"unsupported audio format: {song_path.suffix}")
    pipeline.set_song(pid, video_dir, song_path)
    return {"ok": True}


@router.get("/projects/{pid}/jobs")
def project_jobs(pid: str, active: bool = False) -> list[dict]:
    resolve_project(pid)
    return jobs.list_jobs(pid, active_only=active)


@router.get("/projects/{pid}/logs")
def logs_list(pid: str) -> dict:
    """This project's persisted backend log records (AI calls, prompts, errors).
    Survives restarts. New records also stream live over the SSE 'log' event."""
    resolve_project(pid)
    return {"records": logbuffer.records(pid)}


@router.post("/projects/{pid}/logs/clear")
def logs_clear(pid: str) -> dict:
    resolve_project(pid)
    logbuffer.clear(pid)
    return {"ok": True}


class NotifyRequest(BaseModel):
    event: str
    data: dict = {}


@router.post("/projects/{pid}/notify")
def project_notify(pid: str, body: NotifyRequest) -> dict:
    """Internal hook: lets the MCP server (separate process) poke the UI."""
    resolve_project(pid)
    broadcaster.publish(pid, body.event, body.data)
    return {"ok": True}


@router.get("/projects/{pid}/events")
async def project_events(pid: str) -> StreamingResponse:
    resolve_project(pid)

    async def stream():
        q = broadcaster.subscribe(pid)
        try:
            yield sse_format({"event": "hello", "data": {}})
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=25)
                    if payload is None:  # server shutting down
                        break
                    yield sse_format(payload)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            broadcaster.unsubscribe(pid, q)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
