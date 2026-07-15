"""Background job queue.

Heavy work (ffmpeg, librosa, agy) runs in worker threads with bounded
concurrency per job kind so the event loop never blocks. Job progress is
kept in memory and mirrored to the UI over SSE."""
from __future__ import annotations

import itertools
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .. import logbuffer
from ..events import broadcaster

_id_counter = itertools.count(1)
_jobs: dict[int, "Job"] = {}
_jobs_lock = threading.Lock()

# Separate pools: ffmpeg is CPU/IO heavy, agy calls are network-bound, and
# face detection (ONNX on CPU) gets a single worker so it neither competes
# with ffmpeg nor loads the model concurrently.
_pools = {
    "media": ThreadPoolExecutor(max_workers=2, thread_name_prefix="media"),
    "ai": ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai"),
    "audio": ThreadPoolExecutor(max_workers=1, thread_name_prefix="audio"),
    "faces": ThreadPoolExecutor(max_workers=1, thread_name_prefix="faces"),
}


@dataclass
class Job:
    id: int
    pid: str
    kind: str  # e.g. "frames", "proxy", "analyze", "song"
    label: str
    status: str = "queued"  # queued | running | done | error
    progress: float = 0.0
    message: str = ""
    video_id: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "video_id": self.video_id,
        }


def _emit(job: Job) -> None:
    broadcaster.publish(job.pid, "job", job.to_dict())


def submit(
    pid: str,
    kind: str,
    label: str,
    fn: Callable[["Job"], None],
    pool: str = "media",
    video_id: int | None = None,
) -> Job:
    job = Job(id=next(_id_counter), pid=pid, kind=kind, label=label, video_id=video_id)
    with _jobs_lock:
        _jobs[job.id] = job
    _emit(job)

    def run() -> None:
        job.status = "running"
        _emit(job)
        try:
            with logbuffer.use_project(job.pid):
                fn(job)
            job.status = "done"
            job.progress = 1.0
        except Exception as exc:  # noqa: BLE001 - report any failure to the UI
            job.status = "error"
            job.message = str(exc)
            traceback.print_exc()
        _emit(job)

    _pools[pool].submit(run)
    return job


def update(job: Job, progress: float | None = None, message: str | None = None) -> None:
    if progress is not None:
        job.progress = progress
    if message is not None:
        job.message = message
    _emit(job)


def list_jobs(pid: str, active_only: bool = False) -> list[dict]:
    with _jobs_lock:
        jobs = [j for j in _jobs.values() if j.pid == pid]
    if active_only:
        jobs = [j for j in jobs if j.status in ("queued", "running")]
    return [j.to_dict() for j in sorted(jobs, key=lambda j: j.id)]


def cancel_queued() -> None:
    """Drop queued (not yet started) jobs so process exit isn't held up by a
    long backlog; the pools' worker threads are non-daemon and the interpreter
    joins them at exit. Jobs already running finish their current step.
    Only called from the shutdown signal handler — pools are unusable after."""
    for pool in _pools.values():
        pool.shutdown(wait=False, cancel_futures=True)


def has_active(pid: str, kind: str, video_id: int | None = None) -> bool:
    with _jobs_lock:
        return any(
            j.pid == pid
            and j.kind == kind
            and j.status in ("queued", "running")
            and (video_id is None or j.video_id == video_id)
            for j in _jobs.values()
        )
