"""Scan a directory for video files and read their metadata with ffprobe."""
from __future__ import annotations

import hashlib
import json
import re
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
    # Curated container/stream tags (camera make/model, lens, software,
    # location, plus any other tags under "tags"). {} when the file has none.
    meta: dict


# Container tags that are pure technical plumbing rather than "clip metadata"
# worth surfacing; excluded from ProbeResult.meta (some are promoted separately).
_NOISE_TAGS = {
    "handler_name", "vendor_id", "language", "encoder", "software",
    "compatible_brands", "major_brand", "minor_version", "timecode",
    "creation_time", "com.apple.quicktime.creationdate",
    "make", "com.apple.quicktime.make", "com.android.manufacturer",
    "model", "com.apple.quicktime.model", "com.android.model",
    "com.apple.quicktime.software", "com.android.version",
    "com.apple.quicktime.location.iso6709", "location", "location-eng",
}


def _parse_camera_comment(text: str) -> tuple[str | None, str | None] | None:
    """Fujifilm/Nikon/Panasonic/Olympus often leave make/model blank and write
    "<make> DIGITAL CAMERA <model>" in the comment instead (e.g. "FUJIFILM
    DIGITAL CAMERA X-T2"). Split that into (make, model); return None when the
    text isn't such a signature (nothing usable on either side)."""
    parts = re.split(r"\bDIGITAL\s+(?:STILL\s+)?CAMERA\b", text, maxsplit=1, flags=re.IGNORECASE)
    if len(parts) != 2:
        return None
    make = parts[0].strip() or None
    model = parts[1].strip() or None
    return (make, model) if (make or model) else None


def extract_meta(tags: dict) -> dict:
    """Pull EXIF-ish fields out of ffprobe's format/stream tag dict. Camera and
    phone containers spell these keys many ways, so try the common aliases and
    keep every other (non-noise) tag under "tags" so nothing is silently lost."""
    used: set[str] = set()

    def pick(*keys: str) -> str | None:
        for k in keys:
            v = tags.get(k)
            if v and str(v).strip():
                used.add(k)
                return str(v).strip()
        return None

    make = pick("make", "com.apple.quicktime.make", "com.android.manufacturer")
    model = pick("model", "com.apple.quicktime.model", "com.android.model")
    if not make and not model:  # camera identity hidden in a comment string?
        for k in ("comment", "com.apple.quicktime.comment", "description"):
            v = tags.get(k)
            if v and (parsed := _parse_camera_comment(str(v))):
                make, model = parsed
                used.add(k)
                break
    # Note: the codec-level "encoder" tag (e.g. "AVC Coding") is plumbing, not
    # camera software, so it is not a software source — it stays out of meta.
    software = pick("com.apple.quicktime.software", "software", "com.android.version")
    location = pick("com.apple.quicktime.location.ISO6709", "location", "location-eng")
    lens = pick("com.apple.quicktime.lens", "lens", "lens_model", "lensmodel")
    if lens is None:  # rarely in the container; fall back to any lens-ish key
        for k, v in tags.items():
            if "lens" in k.lower() and str(v).strip():
                lens = str(v).strip()
                used.add(k)
                break

    meta: dict = {}
    for key, val in (
        ("make", make), ("model", model), ("lens", lens),
        ("software", software), ("location", location),
    ):
        if val:
            meta[key] = val

    # Leftover tags, minus noise/consumed keys and the language-suffixed "-eng"
    # duplicates QuickTime emits alongside their base key.
    extra: dict = {}
    for k, v in tags.items():
        val = str(v).strip()
        if not val or k in used or k.lower() in _NOISE_TAGS:
            continue
        if k.lower().endswith("-eng") and str(tags.get(k[:-4], "")).strip() == val:
            continue
        extra[k] = val
    if extra:
        meta["tags"] = extra
    return meta


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
    # creationdate (QuickTime) carries the timezone offset; prefer it over the
    # UTC-normalized creation_time when present.
    shot_at = tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time")

    return ProbeResult(
        duration=duration,
        fps=fps,
        width=int(video_stream.get("width") or 0),
        height=int(video_stream.get("height") or 0),
        codec=video_stream.get("codec_name") or "",
        pix_fmt=video_stream.get("pix_fmt") or "",
        shot_at=shot_at,
        meta=extract_meta(tags),
    )


def needs_proxy(probe_result: ProbeResult) -> bool:
    if probe_result.codec not in BROWSER_SAFE_CODECS:
        return True
    # 10-bit H.264 does not decode in browsers.
    return "10" in probe_result.pix_fmt


def cache_key_for(rel_path: str) -> str:
    return hashlib.md5(rel_path.encode()).hexdigest()[:12]
