"""Derived media generation with ffmpeg: analysis frames, grid thumbnail,
filmstrip for the trim UI, and browser-playable H.264 proxies.

Frame count/size and proxy quality come from the user settings. Everything is
cached under <video_dir>/.montage-cache/<cache_key>/ and regenerated only if
missing (the re-extract action deletes the cache first)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from .. import settings


def frame_count_for(duration: float) -> int:
    f = settings.get().frames
    lo, hi = min(f.min_count, f.max_count), max(f.min_count, f.max_count)
    extra = int(duration // f.seconds_per_frame) if f.seconds_per_frame > 0 else 0
    return max(lo, min(hi, lo + extra))


def frame_timestamps(duration: float, count: int) -> list[float]:
    if duration <= 0:
        return [0.0] * count
    # Evenly spaced, avoiding the very start/end (often black or shaky).
    step = duration / (count + 1)
    return [step * (i + 1) for i in range(count)]


def _run_ffmpeg(args: list[str], timeout: int = 300) -> None:
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {out.stderr.strip()[:400]}")


def extract_frame(video: Path, at: float, dest: Path, width: int | None = None, quality: int | None = None) -> None:
    f = settings.get().frames
    _run_ffmpeg(
        [
            "-ss", f"{at:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={width or f.width}:-2",
            "-q:v", str(quality or f.jpeg_quality), str(dest),
        ]
    )


def extract_analysis_frames(video: Path, duration: float, cache: Path) -> list[Path]:
    cache.mkdir(parents=True, exist_ok=True)
    count = frame_count_for(duration)
    paths = []
    for i, ts in enumerate(frame_timestamps(duration, count)):
        dest = cache / f"frame_{i:02d}.jpg"
        if not dest.exists():
            extract_frame(video, ts, dest)
        paths.append(dest)
    return paths


def make_thumbnail(video: Path, duration: float, cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "thumb.jpg"
    if not dest.exists():
        extract_frame(video, max(0.0, duration * 0.25), dest, width=480)
    return dest


def make_filmstrip(video: Path, duration: float, cache: Path) -> Path:
    """One wide JPEG of N tiles, used as the TrimBar background."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "filmstrip.jpg"
    if dest.exists():
        return dest
    if duration <= 0:
        raise RuntimeError("cannot build filmstrip for zero-duration video")
    tiles = settings.get().frames.filmstrip_tiles
    fps = tiles / duration
    _run_ffmpeg(
        [
            "-i", str(video),
            "-vf", f"fps={fps:.6f},scale=160:-2,tile={tiles}x1",
            "-frames:v", "1", "-q:v", "5", str(dest),
        ],
        timeout=600,
    )
    return dest


def make_proxy(video: Path, cache: Path) -> Path:
    """H.264 + AAC proxy for browser playback of unfriendly codecs."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "proxy.mp4"
    if dest.exists():
        return dest
    height = settings.get().frames.proxy_height
    tmp = cache / "proxy.tmp.mp4"
    _run_ffmpeg(
        [
            "-i", str(video),
            "-vf", f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(tmp),
        ],
        timeout=1800,
    )
    tmp.rename(dest)
    return dest


def make_preview(video: Path, cache: Path) -> Path:
    """Small silent H.264 with dense keyframes: cheap to decode and quick to
    seek, used by the montage preview player in low-res mode."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "preview.mp4"
    if dest.exists():
        return dest
    height = settings.get().frames.preview_height
    tmp = cache / "preview.tmp.mp4"
    _run_ffmpeg(
        [
            "-i", str(video),
            "-vf", f"scale=-2:{height}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
            "-g", "30",
            "-pix_fmt", "yuv420p",
            "-an",
            "-movflags", "+faststart",
            str(tmp),
        ],
        timeout=1800,
    )
    tmp.rename(dest)
    return dest


def clear_derived_frames(cache: Path) -> None:
    """Delete analysis frames + filmstrip + thumbnail + preview so the next
    media job regenerates them with the current settings. The preview matters:
    it must honor a changed preview_height, both for the montage SD player and
    as the video the AI analyzes in video mode. Only the (expensive) proxy is
    kept."""
    if not cache.is_dir():
        return
    for p in cache.glob("frame_*.jpg"):
        p.unlink(missing_ok=True)
    (cache / "filmstrip.jpg").unlink(missing_ok=True)
    (cache / "thumb.jpg").unlink(missing_ok=True)
    (cache / "preview.mp4").unlink(missing_ok=True)
