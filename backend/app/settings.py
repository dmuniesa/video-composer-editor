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
    # Small silent H.264 used by the montage preview player in "SD" mode and
    # attached to the AI analysis when it runs in video mode (AnalysisSettings
    # .agy_media). Changing it takes effect after a re-extract.
    preview_height: int = Field(480, ge=144, le=720)


class AISettings(BaseModel):
    """Which AI analyzes the frames.

    provider:
      auto   - Antigravity CLI if installed, else OpenAI endpoint if configured
      agy    - always the Antigravity CLI
      openai - always the OpenAI-compatible endpoint
      off    - disable AI analysis
    """

    provider: str = Field("auto", pattern="^(auto|agy|openai|off)$")
    # --dangerously-skip-permissions is required since agy 1.1.2: in headless
    # (-p) mode its agent sometimes re-reads the @-attached frames with its
    # read_file tool, which auto-denies without the flag (allow-rules in agy's
    # settings.json fail with "context canceled"), returning empty output.
    agy_cmd: str = "agy --dangerously-skip-permissions -p"
    # Which model agy uses, passed as `--model` (inserted BEFORE -p, since agy
    # swallows flags placed after the print flag into the prompt). Empty = omit
    # the flag and let agy use its own default. Must match one of agy's known
    # model names exactly (run `agy models`), e.g. "Gemini 3.5 Flash (High)".
    agy_model: str = ""
    openai_base_url: str = ""  # e.g. https://api.z.ai/api/paas/v4
    openai_api_key: str = ""
    openai_model: str = ""  # e.g. glm-4.6v-flash
    timeout_s: int = Field(300, ge=10, le=1800)


class AnalysisSettings(BaseModel):
    """Which optional aspects the per-clip AI analysis extracts, besides the
    always-on description/score/hashtags. Disable an aspect if the provider
    handles it poorly: it is then neither requested in the analysis prompt nor
    shown in the UI nor used by the composer. Stored values are kept, so
    re-enabling an aspect brings old results back without re-analyzing."""

    mood: bool = True  # emotional tone words (happy, calm, epic...)
    energy: bool = True  # motion/action level: low/medium/high
    scene: bool = True  # scene label + time of day + shot type
    people_in_prompt: bool = True  # feed named people to the analysis prompt
    # Best moments as time ranges, suggested in the clip detail view. Only
    # extracted in video mode (from frames the AI can't judge times).
    highlights: bool = True
    # How agy receives the clip: "video" attaches the low-res preview.mp4
    # (sees motion, enables highlights; falls back to frames for clips longer
    # than ai.VIDEO_ATTACH_MAX_S or when the preview is missing) — "frames"
    # sends sampled JPEGs. OpenAI-compatible providers always get frames.
    agy_media: str = Field("video", pattern="^(video|frames)$")


class LyricsSettings(BaseModel):
    """Optional deeper music analysis: transcribe the song's lyrics and derive
    where the vocals are, so both the Music page and the AI composer know
    verses/choruses by their words and can spot melody-only (instrumental)
    passages.

    provider:
      auto    - local Whisper if faster-whisper is installed, else the
                Antigravity CLI (Gemini) if available
      whisper - local faster-whisper (pip install faster-whisper); private,
                precise timestamps, but slow on CPU
      agy     - Gemini listens to the song through the Antigravity CLI;
                fast and needs no local model, but the audio is uploaded to
                Google and timestamps are approximate (~1s)

    Disabled by default because transcription takes a while either way."""

    enabled: bool = False
    provider: str = Field("auto", pattern="^(auto|whisper|agy)$")
    # Whisper model size: tiny/base/small/medium/large-v3 (or any CTranslate2
    # model name faster-whisper accepts). Bigger = better lyrics, slower.
    whisper_model: str = "small"
    # ISO-639-1 code ("es", "en"...); empty = auto-detect.
    language: str = ""
    # A gap without vocals at least this long counts as an instrumental part.
    min_instrumental_gap: float = Field(5.0, ge=2, le=60)


class FacesSettings(BaseModel):
    """People detection (faces) in the footage. Requires the optional deps
    (pip install insightface onnxruntime opencv-python-headless).

    model_pack: InsightFace model pack, auto-downloaded on first use to
    ~/.insightface/models/. buffalo_l (~280 MB) is the most accurate;
    buffalo_s (~30 MB) is faster on weak CPUs."""

    model_pack: str = Field("buffalo_l", pattern="^(buffalo_l|buffalo_s)$")
    # One frame sampled every N seconds for face detection...
    frame_interval_s: float = Field(2.0, ge=0.5, le=30)
    # ...capped at this many frames per video (long clips sample sparser).
    max_frames: int = Field(40, ge=5, le=200)


class ComposerSettings(BaseModel):
    """Who auto-composes the timeline from the Montage page.

    provider:
      mcp    - external Claude via MCP (backend/mcp_server.py); the in-app
               Auto-compose button stays disabled
      agy    - one-shot prompt through the Antigravity CLI
      openai - one-shot prompt through the OpenAI-compatible endpoint

    agy/openai reuse the credentials from AISettings (agy_cmd,
    openai_base_url/api_key/model, timeout_s)."""

    provider: str = Field("mcp", pattern="^(mcp|agy|openai)$")


class Settings(BaseModel):
    frames: FrameSettings = Field(default_factory=FrameSettings)
    ai: AISettings = Field(default_factory=AISettings)
    analysis: AnalysisSettings = Field(default_factory=AnalysisSettings)
    composer: ComposerSettings = Field(default_factory=ComposerSettings)
    lyrics: LyricsSettings = Field(default_factory=LyricsSettings)
    faces: FacesSettings = Field(default_factory=FacesSettings)
    # Verbose backend logging: captures full AI prompts and raw model responses
    # in the Logs tab. Env var MONTAGE_LOG_LEVEL, when set, overrides this.
    debug_logging: bool = False


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
