"""Timeline mutations with validation, shared by the REST API and the MCP
server so both enforce the same rules (bounds, overlap rejection)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import TimelineClip, Track, Video

EPS = 1e-6


class TimelineError(ValueError):
    pass


def ensure_default_tracks(db: Session, count: int = 2) -> list[Track]:
    tracks = list(db.scalars(select(Track).order_by(Track.index)))
    while len(tracks) < count:
        track = Track(index=len(tracks), name=f"V{len(tracks) + 1}")
        db.add(track)
        tracks.append(track)
    db.flush()
    return tracks


def add_track(db: Session) -> Track:
    tracks = list(db.scalars(select(Track).order_by(Track.index)))
    track = Track(index=len(tracks), name=f"V{len(tracks) + 1}")
    db.add(track)
    db.flush()
    return track


def remove_track(db: Session, track_id: int) -> None:
    track = db.get(Track, track_id)
    if track is None:
        raise TimelineError(f"track {track_id} not found")
    db.delete(track)
    db.flush()
    for i, t in enumerate(db.scalars(select(Track).order_by(Track.index))):
        t.index = i
    db.flush()


def _check_overlap(
    db: Session, track_id: int, start: float, end: float, ignore_clip_id: int | None = None
) -> None:
    clips = db.scalars(select(TimelineClip).where(TimelineClip.track_id == track_id))
    for c in clips:
        if ignore_clip_id is not None and c.id == ignore_clip_id:
            continue
        c_end = c.timeline_start + c.duration
        if start < c_end - EPS and end > c.timeline_start + EPS:
            raise TimelineError(
                f"overlaps clip {c.id} ({c.timeline_start:.2f}-{c_end:.2f}s) on this track"
            )


def resolve_track(db: Session, ref: int, by_index: bool = False) -> Track:
    """Track ids and 0-based indexes overlap numerically, so the caller must
    say which one it means. The REST API always uses ids; the MCP server
    exposes 0-based indexes (falling back to id when no index matches)."""
    track = None
    if by_index:
        track = db.scalar(select(Track).where(Track.index == ref))
    if track is None:
        track = db.get(Track, ref)
    if track is None:
        raise TimelineError(f"track {ref} not found")
    return track


def place_clip(
    db: Session,
    video_id: int,
    track_ref: int,
    timeline_start: float,
    source_in: float,
    source_out: float,
    placed_by: str = "user",
    track_by_index: bool = False,
) -> TimelineClip:
    video = db.get(Video, video_id)
    if video is None:
        raise TimelineError(f"video {video_id} not found")
    track = resolve_track(db, track_ref, by_index=track_by_index)
    if timeline_start < -EPS:
        raise TimelineError("timeline_start must be >= 0")
    if source_out - source_in <= EPS:
        raise TimelineError("source_out must be greater than source_in")
    if source_in < -EPS or (video.duration and source_out > video.duration + 0.05):
        raise TimelineError(
            f"source range {source_in:.2f}-{source_out:.2f}s outside video duration {video.duration:.2f}s"
        )
    duration = source_out - source_in
    _check_overlap(db, track.id, timeline_start, timeline_start + duration)
    clip = TimelineClip(
        track_id=track.id,
        video_id=video_id,
        timeline_start=max(0.0, timeline_start),
        source_in=source_in,
        source_out=source_out,
        placed_by=placed_by,
    )
    db.add(clip)
    db.flush()
    return clip


def update_clip(
    db: Session,
    clip_id: int,
    timeline_start: float | None = None,
    track_ref: int | None = None,
    source_in: float | None = None,
    source_out: float | None = None,
    track_by_index: bool = False,
) -> TimelineClip:
    clip = db.get(TimelineClip, clip_id)
    if clip is None:
        raise TimelineError(f"clip {clip_id} not found")
    video = db.get(Video, clip.video_id)

    new_start = clip.timeline_start if timeline_start is None else timeline_start
    new_in = clip.source_in if source_in is None else source_in
    new_out = clip.source_out if source_out is None else source_out
    new_track_id = (
        clip.track_id
        if track_ref is None
        else resolve_track(db, track_ref, by_index=track_by_index).id
    )

    if new_start < -EPS:
        raise TimelineError("timeline_start must be >= 0")
    if new_out - new_in <= EPS:
        raise TimelineError("source_out must be greater than source_in")
    if new_in < -EPS or (video and video.duration and new_out > video.duration + 0.05):
        raise TimelineError("source range outside video duration")
    _check_overlap(db, new_track_id, new_start, new_start + (new_out - new_in), ignore_clip_id=clip.id)

    clip.timeline_start = max(0.0, new_start)
    clip.source_in = new_in
    clip.source_out = new_out
    clip.track_id = new_track_id
    db.flush()
    return clip


def remove_clip(db: Session, clip_id: int) -> None:
    clip = db.get(TimelineClip, clip_id)
    if clip is None:
        raise TimelineError(f"clip {clip_id} not found")
    db.delete(clip)
    db.flush()


def clear_track(db: Session, track_ref: int, track_by_index: bool = False) -> int:
    track = resolve_track(db, track_ref, by_index=track_by_index)
    count = 0
    for clip in list(track.clips):
        db.delete(clip)
        count += 1
    db.flush()
    return count


def timeline_state(db: Session) -> dict:
    tracks = ensure_default_tracks(db)
    return {
        "tracks": [
            {
                "id": t.id,
                "index": t.index,
                "name": t.name,
                "clips": [
                    {
                        "id": c.id,
                        "video_id": c.video_id,
                        "timeline_start": c.timeline_start,
                        "source_in": c.source_in,
                        "source_out": c.source_out,
                        "duration": c.duration,
                        "placed_by": c.placed_by,
                    }
                    for c in t.clips
                ],
            }
            for t in tracks
        ]
    }
