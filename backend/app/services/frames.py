"""Derived media generation with ffmpeg: analysis frames, grid thumbnail,
filmstrip for the trim UI, and browser-playable H.264 proxies.

Everything is cached under <video_dir>/.montage-cache/<cache_key>/ and
regenerated only if missing."""
from __future__ import annotations

import subprocess
from pathlib import Path

FRAME_MIN, FRAME_MAX = 3, 10
FILMSTRIP_TILES = 20
FILMSTRIP_TILE_WIDTH = 160


def frame_count_for(duration: float) -> int:
    return max(FRAME_MIN, min(FRAME_MAX, 3 + int(duration // 5)))


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


def extract_frame(video: Path, at: float, dest: Path, width: int = 640) -> None:
    _run_ffmpeg(
        [
            "-ss", f"{at:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", f"scale={width}:-2",
            "-q:v", "3", str(dest),
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
    """One wide JPEG of FILMSTRIP_TILES tiles, used as TrimBar background."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "filmstrip.jpg"
    if dest.exists():
        return dest
    if duration <= 0:
        raise RuntimeError("cannot build filmstrip for zero-duration video")
    fps = FILMSTRIP_TILES / duration
    _run_ffmpeg(
        [
            "-i", str(video),
            "-vf",
            f"fps={fps:.6f},scale={FILMSTRIP_TILE_WIDTH}:-2,tile={FILMSTRIP_TILES}x1",
            "-frames:v", "1", "-q:v", "5", str(dest),
        ],
        timeout=600,
    )
    return dest


def make_proxy(video: Path, cache: Path) -> Path:
    """720p H.264 + AAC proxy for browser playback of unfriendly codecs."""
    cache.mkdir(parents=True, exist_ok=True)
    dest = cache / "proxy.mp4"
    if dest.exists():
        return dest
    tmp = cache / "proxy.tmp.mp4"
    _run_ffmpeg(
        [
            "-i", str(video),
            "-vf", "scale=-2:720",
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
