"""Scan a directory for video files and read their metadata with ffprobe."""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".mts", ".m2ts", ".3gp", ".mkv", ".webm", ".wmv"}
# Codecs Chrome/Firefox can play directly; anything else gets an H.264 proxy.
BROWSER_SAFE_CODECS = {"h264", "vp8", "vp9", "av1"}


@dataclass
class ProbeResult:
    duration: float
    fps: float
    width: int
    height: int
    codec: str
    pix_fmt: str
    shot_at: str | None


def find_videos(video_dir: Path) -> list[Path]:
    files: list[Path] = []
    for p in sorted(video_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in VIDEO_EXTENSIONS:
            continue
        if ".montage-cache" in p.parts:
            continue
        files.append(p)
    return files


def probe(path: Path) -> ProbeResult:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {path.name}: {out.stderr.strip()[:300]}")
    data = json.loads(out.stdout)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"), None
    )
    if video_stream is None:
        raise RuntimeError(f"no video stream in {path.name}")

    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or video_stream.get("duration") or 0)

    fps = 0.0
    rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
    try:
        num, den = rate.split("/")
        if float(den) != 0:
            fps = float(num) / float(den)
    except ValueError:
        pass

    tags = {**fmt.get("tags", {}), **video_stream.get("tags", {})}
    shot_at = tags.get("creation_time")

    return ProbeResult(
        duration=duration,
        fps=fps,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        codec=video_stream.get("codec_name") or "",
        pix_fmt=video_stream.get("pix_fmt") or "",
        shot_at=shot_at,
    )


def needs_proxy(probe_result: ProbeResult) -> bool:
    if probe_result.codec not in BROWSER_SAFE_CODECS:
        return True
    # 10-bit H.264 does not decode in browsers.
    return "10" in probe_result.pix_fmt


def cache_key_for(rel_path: str) -> str:
    return hashlib.md5(rel_path.encode()).hexdigest()[:12]
