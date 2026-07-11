"""User-editable application settings, persisted as JSON in the user's home
directory (override the location with MONTAGE_SETTINGS, e.g. in tests).

Frame settings apply to future extractions; the Settings page offers a
re-extract action per project. AI settings select which provider analyzes the
video frames and labels song sections."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from pydantic import BaseModel, Field


def settings_path() -> Path:
    return Path(
        os.environ.get(
            "MONTAGE_SETTINGS", str(Path.home() / ".video-montage-composer" / "settings.json")
        )
    )


class FrameSettings(BaseModel):
    """How many frames are sampled per video for AI analysis, and their size."""

    min_count: int = Field(3, ge=1, le=50)
    max_count: int = Field(10, ge=1, le=50)
    # one extra frame for every N seconds of video (between min and max)
    seconds_per_frame: float = Field(5.0, ge=0.5, le=120)
    width: int = Field(640, ge=160, le=1920)
    jpeg_quality: int = Field(3, ge=1, le=10)  # ffmpeg -q:v (lower = better)
    filmstrip_tiles: int = Field(20, ge=5, le=60)
    proxy_height: int = Field(720, ge=240, le=1080)


class AISettings(BaseModel):
    """Which AI analyzes the frames.

    provider:
      auto   - Antigravity CLI if installed, else OpenAI endpoint if configured
      agy    - always the Antigravity CLI
      openai - always the OpenAI-compatible endpoint
      off    - disable AI analysis
    """

    provider: str = Field("auto", pattern="^(auto|agy|openai|off)$")
    agy_cmd: str = "agy --headless -p"
    openai_base_url: str = ""  # e.g. https://api.z.ai/api/paas/v4
    openai_api_key: str = ""
    openai_model: str = ""  # e.g. glm-4.6v-flash
    timeout_s: int = Field(300, ge=10, le=1800)


class Settings(BaseModel):
    frames: FrameSettings = Field(default_factory=FrameSettings)
    ai: AISettings = Field(default_factory=AISettings)


_lock = threading.Lock()
_cache: Settings | None = None
_cache_path: Path | None = None


def get() -> Settings:
    global _cache, _cache_path
    path = settings_path()
    with _lock:
        if _cache is None or _cache_path != path:
            try:
                _cache = Settings.model_validate(json.loads(path.read_text()))
            except (OSError, ValueError):
                _cache = Settings()
            _cache_path = path
        return _cache


def save(settings: Settings) -> Settings:
    global _cache, _cache_path
    path = settings_path()
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(settings.model_dump_json(indent=2))
        _cache = settings
        _cache_path = path
    return settings


def reload() -> Settings:
    """Drop the cache (used by tests after changing MONTAGE_SETTINGS)."""
    global _cache
    with _lock:
        _cache = None
    return get()
