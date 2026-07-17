"""In-memory per-project undo/redo snapshots of the timeline (tracks + clips).

Lives only in the API process and is lost on restart. The MCP server is a
separate process writing the DB directly, so its edits bypass these stacks;
the snapshot taken before the next REST mutation still captures them.
"""
from __future__ import annotations

import copy
import threading

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import TimelineClip, Track, Video

MAX_DEPTH = 50

_stacks: dict[str, dict[str, list[dict]]] = {}  # pid -> {"undo": [...], "redo": [...]}
_lock = threading.Lock()


def _project(pid: str) -> dict[str, list[dict]]:
    return _stacks.setdefault(pid, {"undo": [], "redo": []})


def snapshot(db: Session) -> dict:
    """Pure read of the timeline as plain dicts (unlike ops.timeline_state,
    which creates default tracks as a side effect)."""
    tracks = []
    for t in db.scalars(select(Track).order_by(Track.index)):
        tracks.append(
            {
                "id": t.id,
                "index": t.index,
                "name": t.name,
                "clips": [
                    {
                        "id": c.id,
                        "track_id": c.track_id,
                        "video_id": c.video_id,
                        "timeline_start": c.timeline_start,
                        "source_in": c.source_in,
                        "source_out": c.source_out,
                        "speed": c.speed,
                        "placed_by": c.placed_by,
                    }
                    for c in t.clips
                ],
            }
        )
    return {"tracks": tracks}


def record(pid: str, snap: dict) -> None:
    """Push a pre-mutation snapshot onto the undo stack; a new edit
    invalidates anything that was redoable."""
    with _lock:
        stacks = _project(pid)
        stacks["undo"].append(snap)
        del stacks["undo"][:-MAX_DEPTH]
        stacks["redo"].clear()


def can_undo(pid: str) -> bool:
    with _lock:
        return bool(_stacks.get(pid, {}).get("undo"))


def can_redo(pid: str) -> bool:
    with _lock:
        return bool(_stacks.get(pid, {}).get("redo"))


def peek(pid: str, kind: str) -> dict | None:
    with _lock:
        stack = _stacks.get(pid, {}).get(kind)
        return copy.deepcopy(stack[-1]) if stack else None


def commit_undo(pid: str, current: dict) -> None:
    with _lock:
        stacks = _project(pid)
        if stacks["undo"]:
            stacks["undo"].pop()
            stacks["redo"].append(current)


def commit_redo(pid: str, current: dict) -> None:
    with _lock:
        stacks = _project(pid)
        if stacks["redo"]:
            stacks["redo"].pop()
            stacks["undo"].append(current)


def restore(db: Session, snap: dict) -> None:
    """Replace the whole timeline with the snapshot, preserving original ids
    (int PKs without AUTOINCREMENT, so explicit inserts are safe)."""
    db.execute(delete(TimelineClip))
    db.execute(delete(Track))
    db.flush()
    for t in snap["tracks"]:
        db.add(Track(id=t["id"], index=t["index"], name=t["name"]))
    db.flush()
    existing_videos = set(db.scalars(select(Video.id)))
    for t in snap["tracks"]:
        for c in t["clips"]:
            # the source video may have been deleted after the snapshot
            if c["video_id"] not in existing_videos:
                continue
            db.add(
                TimelineClip(
                    id=c["id"],
                    track_id=c["track_id"],
                    video_id=c["video_id"],
                    timeline_start=c["timeline_start"],
                    source_in=c["source_in"],
                    source_out=c["source_out"],
                    speed=c["speed"],
                    placed_by=c["placed_by"],
                )
            )
    db.flush()
    db.expire_all()
