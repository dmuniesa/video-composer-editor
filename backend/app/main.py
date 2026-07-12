"""FastAPI application: API + media + (in production) the built frontend."""
from __future__ import annotations

import asyncio
import logging
import signal
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import export, media, music, projects, settings_api, timeline, videos
from .events import broadcaster
from .logbuffer import BufferHandler, apply_level
from .services import jobs


def _configure_logging() -> None:
    """Route the app's own logs to the console and the in-app Logs tab.

    Level comes from Settings (the "Verbose logging" toggle) or the
    MONTAGE_LOG_LEVEL env var when set; DEBUG additionally captures the full
    AI prompts and raw model responses (handy for debugging AI analysis)."""
    logger = logging.getLogger("app")
    if not any(isinstance(h, BufferHandler) for h in logger.handlers):
        console = logging.StreamHandler()
        console.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
        )
        logger.addHandler(console)
        logger.addHandler(BufferHandler())  # persists + streams to the Logs tab
    logger.propagate = False  # don't double-log through the root logger
    apply_level()


_configure_logging()

app = FastAPI(title="Beatcut")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _chain_shutdown_signals() -> None:
    """Ctrl+C left uvicorn hanging at "Waiting for connections to close":
    its graceful shutdown waits for open connections, but browser EventSource
    tabs hold the SSE streams open forever. Chain onto uvicorn's own signal
    handlers (installed before the lifespan startup runs) to end the SSE
    streams and drop queued background jobs, then let uvicorn proceed."""
    if threading.current_thread() is not threading.main_thread():
        return  # signals only work in the main thread (e.g. tests' TestClient)

    def chain(sig: int) -> None:
        prev = signal.getsignal(sig)

        def handler(signum, frame):  # noqa: ANN001
            broadcaster.close_all()
            jobs.cancel_queued()
            if callable(prev):
                prev(signum, frame)

        signal.signal(sig, handler)

    for sig in (signal.SIGINT, signal.SIGTERM):
        chain(sig)


@app.on_event("startup")
async def _startup() -> None:
    broadcaster.set_loop(asyncio.get_running_loop())
    _chain_shutdown_signals()


app.include_router(projects.router, prefix="/api")
app.include_router(videos.router, prefix="/api")
app.include_router(music.router, prefix="/api")
app.include_router(timeline.router, prefix="/api")
app.include_router(export.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(media.router)

# Serve the built frontend when it exists (production mode: single process).
_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        candidate = _dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
