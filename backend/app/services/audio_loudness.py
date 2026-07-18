"""Per-clip loudness measurement (EBU R128 / LUFS) via ffmpeg's loudnorm filter,
and project-wide audio normalisation.

Each clip's integrated loudness is measured over its source range, then a
constant gain ``norm_gain_db = target - measured`` is stored on the clip so every
clip lands at the same target loudness when the gains are applied.

This gain is NOT a loudnorm filter applied at render time — the app does not
render video; it exports editor XML (xmeml/fcpxml) and previews client-side. So
normalisation must be pre-computed as a per-clip dB gain and expressed in the
export XML and the preview mix (see export.py / xmeml.py / fcpxml.py and the
frontend preview wiring)."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TimelineClip, Video

# loudnorm prints its measurement as a multi-line JSON block on stderr; grab the
# block that opens with "input_i" (the integrated loudness field).
_LOUDNORM_JSON_RE = re.compile(r'\{\s*"input_i"\s*:.*?\}', re.S)

# Clamp the per-clip normalisation gain so one wildly-quiet clip can't demand an
# absurd boost (which would clip hard and swamp the mix). Matches the UI clamp.
GAIN_MIN_DB = -24.0
GAIN_MAX_DB = 24.0
# Below this measured loudness the input is effectively silent (loudnorm reports
# -inf or -70 for all-gated audio); leave the gain at 0 rather than +inf.
SILENT_LUFS = -70.0


def measure_clip_lufs(video_path: Path, source_in: float, source_out: float) -> float:
    """Integrated loudness (LUFS, EBU R128) of a clip's source range.

    Runs ffmpeg's loudnorm in measurement mode over ``-ss source_in -t dur``
    (fast seek before -i, like frames.extract_frame), decodes to null, and parses
    the JSON block loudnorm prints on stderr. Returns the input integrated
    loudness. Returns -inf for an empty range; the caller treats that as skip."""
    dur = max(0.0, source_out - source_in)
    if dur <= 0:
        return float("-inf")
    args = [
        "-ss", f"{source_in:.3f}",
        "-t", f"{dur:.3f}",
        "-i", str(video_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
        "-f", "null",
        "-",
    ]
    # NOTE: -loglevel must be info (or warning) here, NOT error — loudnorm emits
    # its JSON at info level, so frames._run_ffmpeg (which uses -loglevel error)
    # would suppress it. Capture stderr and parse the block out.
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "info", "-y", *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm failed: {(proc.stderr or '').strip()[-400:]}")
    m = _LOUDNORM_JSON_RE.search(proc.stderr or "")
    if not m:
        raise RuntimeError("loudnorm produced no JSON measurement")
    info = json.loads(m.group(0))
    return float(info["input_i"])


def _clip_video_path(video: Video | None, video_dir: Path) -> Path | None:
    """Absolute media path for a clip's source video, mirroring export._gather."""
    if video is None:
        return None
    base = Path(video.source.path) if video.source is not None else video_dir
    return base / video.rel_path


def normalize_project(db: Session, video_dir: Path, target_lufs: float = -16.0) -> list[dict]:
    """Measure every clip and store ``norm_gain_db = clamp(target - measured)``.

    Clips with no resolvable file, or whose audio measures as silent (-inf / very
    low), keep ``norm_gain_db = 0``. Per-clip failures are captured in the report
    instead of aborting the whole run. The caller is responsible for committing.

    Only ``TimelineClip`` rows are normalised — the background song is a separate
    concept and is intentionally left untouched."""
    clips = list(db.scalars(select(TimelineClip)))
    video_ids = [c.video_id for c in clips]
    videos = {v.id: v for v in db.scalars(select(Video).where(Video.id.in_(video_ids)))} if video_ids else {}
    report: list[dict] = []
    for clip in clips:
        entry: dict = {"clip_id": clip.id}
        path = _clip_video_path(videos.get(clip.video_id), video_dir)
        if path is None or not path.exists():
            clip.norm_gain_db = 0.0
            entry["error"] = "missing media"
            report.append(entry)
            continue
        try:
            measured = measure_clip_lufs(path, clip.source_in, clip.source_out)
        except Exception as exc:  # one bad file must not fail the batch
            clip.norm_gain_db = 0.0
            entry["error"] = str(exc)[:200]
            report.append(entry)
            continue
        if measured == float("-inf") or measured <= SILENT_LUFS:
            clip.norm_gain_db = 0.0
            entry["measured_lufs"] = None
            report.append(entry)
            continue
        gain = target_lufs - measured
        clip.norm_gain_db = max(GAIN_MIN_DB, min(GAIN_MAX_DB, gain))
        entry["measured_lufs"] = round(measured, 2)
        entry["norm_gain_db"] = round(clip.norm_gain_db, 2)
        report.append(entry)
    return report
