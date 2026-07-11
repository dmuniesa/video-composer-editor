"""FastAPI application: API + media + (in production) the built frontend."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import export, media, music, projects, settings_api, timeline, videos
from .events import broadcaster
from .logbuffer import BufferHandler, apply_level


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
        logger.addHandler(BufferHandler())  # feeds /api/logs + the Logs tab
    logger.propagate = False  # don't double-log through the root logger
    apply_level()


_configure_logging()

app = FastAPI(title="Video Montage Composer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _startup() -> None:
    broadcaster.set_loop(asyncio.get_running_loop())


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
