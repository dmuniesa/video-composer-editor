"""Project lifecycle + server-side filesystem browser + jobs + SSE."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import db as dbm
from .. import logbuffer
from ..events import broadcaster, sse_format
from ..models import Project, Song, Source, TimelineClip, Video
from ..services import ai, composer, jobs, native_picker, pipeline
from .deps import resolve_project

router = APIRouter()

AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff"}


class PickRequest(BaseModel):
    kind: str = "dir"  # "dir" | "audio"
    initial: str = ""


@router.post("/fs/pick")
def fs_pick(body: PickRequest) -> dict:
    """Open the OS-native folder/file dialog on the user's desktop and return
    the chosen absolute path (null if cancelled). 501 when no native dialog is
    available, so the UI can fall back to the in-app browser."""
    if not native_picker.available():
        raise HTTPException(501, "native file dialog unavailable")
    kind = body.kind if body.kind in ("dir", "audio") else "dir"
    return {"path": native_picker.pick(kind, body.initial)}


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
    # Storage folder for the project (where montage.db + cache live).
    project_dir: str | None = None
    # Legacy alias: the old "open a folder" flow. When given, the folder is also
    # registered as the project's first footage source.
    video_dir: str | None = None
    name: str = ""


@router.get("/projects")
def projects_list() -> list[dict]:
    out = []
    for pid, project_dir in dbm.list_projects().items():
        path = Path(project_dir)
        if not path.is_dir():
            continue
        name = path.name
        with dbm.open_session(path) as db:
            project = db.scalar(select(Project))
            if project and project.name:
                name = project.name
        out.append({"id": pid, "video_dir": project_dir, "name": name})
    return out


def _get_or_create_project(db, storage: Path, name: str) -> Project:
    project = db.scalar(select(Project))
    if project is None:
        project = Project(name=name or storage.name, video_dir=str(storage.resolve()))
        db.add(project)
        db.commit()
    return project


@router.post("/projects")
def project_create(body: CreateProject) -> dict:
    raw = body.project_dir or body.video_dir
    if not raw:
        raise HTTPException(400, "project_dir is required")
    storage = Path(raw).expanduser()
    if not storage.is_dir():
        raise HTTPException(400, f"not a directory: {storage}")
    pid = dbm.register_project(storage)
    with dbm.open_session(storage) as db:
        _get_or_create_project(db, storage, body.name)
        # Legacy alias: seed the folder itself as the first source so the old
        # single-folder flow (create + scan) keeps working.
        if body.video_dir and db.scalar(select(Source)) is None:
            resolved = str(storage.resolve())
            db.add(Source(path=resolved, label=Path(resolved).name))
            db.commit()
    return project_get(pid)


class ImportProject(BaseModel):
    project_dir: str


@router.post("/projects/import")
def project_import(body: ImportProject) -> dict:
    """Register an existing project storage folder (one that already contains
    .montage-cache/montage.db). The database is self-contained, so importing is
    just adding the folder to the registry."""
    storage = Path(body.project_dir).expanduser()
    if not storage.is_dir():
        raise HTTPException(400, f"not a directory: {storage}")
    if not (dbm.cache_dir_for(storage) / "montage.db").is_file():
        raise HTTPException(400, f"no project found in {storage} (missing .montage-cache/montage.db)")
    pid = dbm.register_project(storage)
    return project_get(pid)


def _source_dict(db, source: Source) -> dict:
    count = db.scalar(
        select(func.count(Video.id)).where(Video.source_id == source.id)
    ) or 0
    return {
        "id": source.id,
        "path": source.path,
        "label": source.label or Path(source.path).name,
        "online": Path(source.path).is_dir(),
        "video_count": count,
    }


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
        sources = [_source_dict(db, s) for s in db.scalars(select(Source).order_by(Source.id))]
        return {
            "id": pid,
            "name": project.name if project else video_dir.name,
            "video_dir": str(video_dir),
            "sources": sources,
            "composition_fps": (project.composition_fps if project else None) or 25.0,
            "composition_width": (project.composition_width if project else None) or 1920,
            "composition_height": (project.composition_height if project else None) or 1080,
            "song_path": song.path if song else None,
            "song_status": song.status if song else None,
            "video_count": total,
            "videos_by_status": by_status,
            "ai_available": ai.available(),
            "ai_provider": ai.provider(),
            "composer_provider": composer.provider(),
            "composer_available": composer.available(),
        }


class AddSource(BaseModel):
    path: str
    label: str | None = None


@router.get("/projects/{pid}/sources")
def sources_list(pid: str) -> list[dict]:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        return [_source_dict(db, s) for s in db.scalars(select(Source).order_by(Source.id))]


@router.post("/projects/{pid}/sources")
def source_add(pid: str, body: AddSource) -> dict:
    video_dir = resolve_project(pid)
    path = Path(body.path).expanduser()
    if not path.is_dir():
        raise HTTPException(400, f"not a directory: {path}")
    resolved = str(path.resolve())
    with dbm.open_session(video_dir) as db:
        if db.scalar(select(Source).where(Source.path == resolved)) is not None:
            raise HTTPException(409, "that folder is already a source of this project")
        source = Source(path=resolved, label=(body.label or path.name))
        db.add(source)
        db.commit()
    pipeline.scan_project(pid, video_dir)
    broadcaster.publish(pid, "videos", {})
    return project_get(pid)


class UpdateSource(BaseModel):
    path: str | None = None
    label: str | None = None


@router.patch("/projects/{pid}/sources/{sid}")
def source_update(pid: str, sid: int, body: UpdateSource) -> dict:
    """Relink a source that moved (or rename it) without losing any per-video
    data: the videos keep their rel_path and cache, only the root path changes."""
    video_dir = resolve_project(pid)
    rescan = False
    with dbm.open_session(video_dir) as db:
        source = db.get(Source, sid)
        if source is None:
            raise HTTPException(404, "source not found")
        if body.path is not None:
            new_path = Path(body.path).expanduser()
            if not new_path.is_dir():
                raise HTTPException(400, f"not a directory: {new_path}")
            resolved = str(new_path.resolve())
            other = db.scalar(
                select(Source).where(Source.path == resolved, Source.id != sid)
            )
            if other is not None:
                raise HTTPException(409, "another source already points at that folder")
            source.path = resolved
            rescan = True
        if body.label is not None:
            source.label = body.label.strip()
        db.commit()
    if rescan:
        # Pick up files added/removed at the new location (existing rows are kept).
        pipeline.scan_project(pid, video_dir)
        broadcaster.publish(pid, "videos", {})
    return project_get(pid)


@router.delete("/projects/{pid}/sources/{sid}")
def source_delete(pid: str, sid: int) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        source = db.get(Source, sid)
        if source is None:
            raise HTTPException(404, "source not found")
        videos = list(db.scalars(select(Video).where(Video.source_id == sid)))
        video_ids = [v.id for v in videos]
        if video_ids:
            # TimelineClip has no cascade to Video; remove clips referencing these.
            for clip in db.scalars(
                select(TimelineClip).where(TimelineClip.video_id.in_(video_ids))
            ):
                db.delete(clip)
        for video in videos:
            cache = dbm.cache_dir_for(video_dir) / video.cache_key
            shutil.rmtree(cache, ignore_errors=True)
            db.delete(video)
        db.delete(source)
        db.commit()
    broadcaster.publish(pid, "videos", {})
    broadcaster.publish(pid, "timeline", {"source": "source-removed"})
    return project_get(pid)


class ProjectUpdate(BaseModel):
    name: str | None = None
    composition_fps: float | None = None
    composition_width: int | None = None
    composition_height: int | None = None


@router.patch("/projects/{pid}")
def project_update(pid: str, body: ProjectUpdate) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        project = db.scalar(select(Project))
        if project is None:
            project = Project(name=video_dir.name, video_dir=str(video_dir))
            db.add(project)
        if body.name is not None:
            name = body.name.strip()
            if not name:
                raise HTTPException(400, "name must not be empty")
            if len(name) > 200:
                raise HTTPException(400, "name must be 200 characters or fewer")
            project.name = name
        if body.composition_fps is not None:
            if not (10 <= body.composition_fps <= 120):
                raise HTTPException(400, "composition_fps must be between 10 and 120")
            project.composition_fps = body.composition_fps
        if body.composition_width is not None:
            if not (16 <= body.composition_width <= 8192):
                raise HTTPException(400, "composition_width must be between 16 and 8192")
            project.composition_width = body.composition_width
        if body.composition_height is not None:
            if not (16 <= body.composition_height <= 8192):
                raise HTTPException(400, "composition_height must be between 16 and 8192")
            project.composition_height = body.composition_height
        db.commit()
    return project_get(pid)


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
