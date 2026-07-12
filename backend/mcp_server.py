"""MCP server exposing the montage project to Claude, so Claude can read the
video analyses + song structure and place clips on the timeline.

Run (stdio transport):
    python backend/mcp_server.py --project /path/to/video/folder

Register with Claude Code:
    claude mcp add montage -- python /abs/path/backend/mcp_server.py --project /path/to/video/folder

It opens the same SQLite database as the web app and, after each mutation,
pokes the web app's SSE channel (best effort) so the browser updates live.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from app import db as dbm, settings  # noqa: E402
from app.models import Song, Video  # noqa: E402
from app.services import lyrics as lyrics_svc  # noqa: E402
from app.services import timeline_ops as ops  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--project", required=True, help="video directory of the project")
parser.add_argument(
    "--api", default=os.environ.get("MONTAGE_API", "http://127.0.0.1:8765"),
    help="base URL of the running web app, used to live-refresh the browser",
)
args = parser.parse_args()

VIDEO_DIR = Path(args.project).expanduser().resolve()
if not VIDEO_DIR.is_dir():
    print(f"error: {VIDEO_DIR} is not a directory", file=sys.stderr)
    sys.exit(1)
PID = dbm.register_project(VIDEO_DIR)

mcp = FastMCP("video-montage")


def _notify() -> None:
    """Tell the web UI (if running) that the timeline changed."""
    try:
        httpx.post(
            f"{args.api}/api/projects/{PID}/notify",
            json={"event": "timeline", "data": {"source": "mcp"}},
            timeout=2,
        )
    except httpx.HTTPError:
        pass


@mcp.tool()
def get_project_summary() -> dict:
    """Overview of the montage project: song duration/BPM/sections, timeline
    tracks, and how many videos are available. Call this first."""
    with dbm.open_session(VIDEO_DIR) as db:
        song = db.scalar(select(Song))
        videos = list(db.scalars(select(Video)))
        state = ops.timeline_state(db)
        db.commit()
        return {
            "video_dir": str(VIDEO_DIR),
            "song": {
                "path": song.path,
                "duration": song.duration,
                "bpm": song.bpm,
                "sections": [
                    {"start": s.start, "end": s.end, "label": s.label, "energy": s.energy}
                    for s in song.sections
                ],
            }
            if song
            else None,
            "tracks": [
                {"id": t["id"], "index": t["index"], "name": t["name"], "clip_count": len(t["clips"])}
                for t in state["tracks"]
            ],
            "video_count": len(videos),
        }


@mcp.tool()
def list_videos(
    min_stars: int = 0, include_unrated: bool = True, hashtag: str = ""
) -> list[dict]:
    """List candidate videos (never includes rejected ones) with their AI
    description, hashtags, user star rating (0-5), AI score (1-10), duration
    in seconds, and the user's hand-picked interesting ranges.

    min_stars: only videos rated at least this many stars.
    include_unrated: also include videos with 0 stars (unrated).
    hashtag: filter to videos containing this hashtag."""
    out = []
    with dbm.open_session(VIDEO_DIR) as db:
        for v in db.scalars(select(Video).order_by(Video.filename)):
            stars = v.rating.stars if v.rating else 0
            if v.rating and v.rating.rejected:
                continue
            if stars < min_stars and not (include_unrated and stars == 0):
                continue
            tags = v.analysis.hashtags if v.analysis else []
            if hashtag and hashtag.lower().lstrip("#") not in tags:
                continue
            out.append(
                {
                    "id": v.id,
                    "filename": v.filename,
                    "duration": v.duration,
                    "stars": stars,
                    "ai_score": v.analysis.ai_score if v.analysis else None,
                    "description": v.analysis.description if v.analysis else "",
                    "hashtags": tags,
                    "ranges": [
                        {"t_in": r.t_in, "t_out": r.t_out, "label": r.label} for r in v.ranges
                    ],
                }
            )
    return out


@mcp.tool()
def get_music_sections() -> list[dict]:
    """Song sections (intro/verse/chorus...) with start/end seconds and
    relative energy 0-1. When lyrics were transcribed, each section also has
    vocal_ratio (0-1, fraction with singing; ~0 = instrumental/melody-only).
    Cut points should usually align with these."""
    with dbm.open_session(VIDEO_DIR) as db:
        song = db.scalar(select(Song))
        if song is None:
            return []
        lyr = song.lyrics if song.lyrics is not None and song.lyrics.status == "ready" else None
        vocals = lyrics_svc.vocal_ranges(lyr.segments) if lyr else None
        return [
            {
                "start": s.start,
                "end": s.end,
                "label": s.label,
                "energy": s.energy,
                **(
                    {"vocal_ratio": lyrics_svc.vocal_ratio(s.start, s.end, vocals)}
                    if vocals is not None
                    else {}
                ),
            }
            for s in song.sections
        ]


@mcp.tool()
def get_lyrics() -> dict:
    """Timestamped lyrics of the song (Whisper transcription) plus the
    melody-only passages. Use them to match footage to what the lyrics say
    and to place calmer/scenic shots over instrumental_ranges. Empty when
    lyrics analysis is disabled in Settings or not transcribed yet."""
    with dbm.open_session(VIDEO_DIR) as db:
        song = db.scalar(select(Song))
        if song is None or song.lyrics is None or song.lyrics.status != "ready":
            return {"available": False, "lines": [], "instrumental_ranges": []}
        vocals = lyrics_svc.vocal_ranges(song.lyrics.segments)
        return {
            "available": True,
            "language": song.lyrics.language,
            "lines": song.lyrics.segments,
            "instrumental_ranges": lyrics_svc.instrumental_ranges(
                vocals, song.duration, settings.get().lyrics.min_instrumental_gap
            ),
        }


@mcp.tool()
def get_beats(start: float = 0.0, end: float = 1e9) -> list[float]:
    """Beat timestamps (seconds) of the song between start and end. Snap clip
    boundaries to these for a montage that cuts on the beat."""
    with dbm.open_session(VIDEO_DIR) as db:
        song = db.scalar(select(Song))
        if song is None:
            return []
        return [b for b in song.beats if start <= b <= end]


@mcp.tool()
def get_timeline() -> dict:
    """Current timeline: tracks with their clips (timeline_start, source
    in/out, duration, video_id)."""
    with dbm.open_session(VIDEO_DIR) as db:
        state = ops.timeline_state(db)
        db.commit()
        return state


@mcp.tool()
def place_clip(
    video_id: int,
    track: int,
    timeline_start: float,
    source_in: float,
    source_out: float,
) -> dict:
    """Place a clip on the timeline. track is a 0-based track index (falls
    back to a track id when no index matches). timeline_start is seconds into the song; source_in/source_out are
    seconds inside the video. Fails if it would overlap an existing clip on
    the same track or exceed the video's duration."""
    with dbm.open_session(VIDEO_DIR) as db:
        try:
            clip = ops.place_clip(
                db, video_id, track, timeline_start, source_in, source_out,
                placed_by="claude", track_by_index=True,
            )
        except ops.TimelineError as exc:
            return {"error": str(exc)}
        db.commit()
        result = {"clip_id": clip.id}
    _notify()
    return result


@mcp.tool()
def move_clip(
    clip_id: int,
    timeline_start: float | None = None,
    track: int | None = None,
    source_in: float | None = None,
    source_out: float | None = None,
) -> dict:
    """Move/retrim an existing clip. Only the provided fields change."""
    with dbm.open_session(VIDEO_DIR) as db:
        try:
            ops.update_clip(db, clip_id, timeline_start, track, source_in, source_out, track_by_index=True)
        except ops.TimelineError as exc:
            return {"error": str(exc)}
        db.commit()
    _notify()
    return {"ok": True}


@mcp.tool()
def remove_clip(clip_id: int) -> dict:
    """Remove one clip from the timeline."""
    with dbm.open_session(VIDEO_DIR) as db:
        try:
            ops.remove_clip(db, clip_id)
        except ops.TimelineError as exc:
            return {"error": str(exc)}
        db.commit()
    _notify()
    return {"ok": True}


@mcp.tool()
def clear_track(track: int) -> dict:
    """Remove every clip from a track (id or 0-based index)."""
    with dbm.open_session(VIDEO_DIR) as db:
        try:
            count = ops.clear_track(db, track, track_by_index=True)
        except ops.TimelineError as exc:
            return {"error": str(exc)}
        db.commit()
    _notify()
    return {"removed": count}


if __name__ == "__main__":
    mcp.run()
