"""Undo/redo history for the montage timeline: unit tests over
timeline_history plus the REST endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db as dbm
from app.main import app
from app.models import TimelineClip, Track, Video
from app.services import timeline_history as history
from app.services import timeline_ops as ops


@pytest.fixture(autouse=True)
def _clean_stacks():
    history._stacks.clear()
    yield
    history._stacks.clear()


@pytest.fixture
def db(tmp_path):
    session = dbm.open_session(tmp_path)
    session.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
    session.commit()
    ops.ensure_default_tracks(session)
    session.commit()
    yield session
    session.close()


# ---- unit: snapshot / restore ----

def test_restore_preserves_ids(db):
    clip = ops.place_clip(db, 1, 0, 0.0, 1.0, 4.0, track_by_index=True)
    db.commit()
    snap = history.snapshot(db)
    track_ids = [t["id"] for t in snap["tracks"]]

    ops.remove_clip(db, clip.id)
    ops.add_track(db)
    db.commit()

    history.restore(db, snap)
    db.commit()
    assert [t.id for t in db.scalars(select(Track).order_by(Track.index))] == track_ids
    clips = list(db.scalars(select(TimelineClip)))
    assert len(clips) == 1
    assert clips[0].id == clip.id
    assert clips[0].source_in == 1.0

    # explicit-id inserts must not break the next autoincrement
    new_clip = ops.place_clip(db, 1, 0, 5.0, 0.0, 2.0, track_by_index=True)
    assert new_clip.id != clip.id


def test_restore_skips_deleted_videos(db):
    ops.place_clip(db, 1, 0, 0.0, 1.0, 4.0, track_by_index=True)
    db.commit()
    snap = history.snapshot(db)

    for c in list(db.scalars(select(TimelineClip))):
        db.delete(c)
    db.delete(db.get(Video, 1))
    db.commit()

    history.restore(db, snap)
    db.commit()
    assert list(db.scalars(select(TimelineClip))) == []
    # tracks still restored
    assert len(list(db.scalars(select(Track)))) == 2


def test_max_depth_cap(db):
    snap = history.snapshot(db)
    for _ in range(history.MAX_DEPTH + 10):
        history.record("p", snap)
    assert len(history._stacks["p"]["undo"]) == history.MAX_DEPTH


def test_record_clears_redo(db):
    snap = history.snapshot(db)
    history.record("p", snap)
    history.commit_undo("p", snap)
    assert history.can_redo("p")
    history.record("p", snap)
    assert not history.can_redo("p")


# ---- REST endpoints ----

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client, tmp_path):
    videos = tmp_path / "proj"
    videos.mkdir()
    res = client.post("/api/projects", json={"video_dir": str(videos)})
    assert res.status_code == 200, res.text
    pid = res.json()["id"]
    session = dbm.open_session(videos)
    session.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
    session.commit()
    session.close()
    return pid


def test_undo_redo_flow(client, project):
    pid = project
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert state["can_undo"] is False and state["can_redo"] is False
    track_id = state["tracks"][0]["id"]

    res = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": 1, "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.0},
    )
    assert res.status_code == 200, res.text
    clip_id = res.json()["id"]

    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert state["can_undo"] is True and state["can_redo"] is False

    # undo removes the clip
    assert client.post(f"/api/projects/{pid}/timeline/undo").status_code == 200
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert all(not t["clips"] for t in state["tracks"])
    assert state["can_undo"] is False and state["can_redo"] is True

    # redo brings it back with the same id
    assert client.post(f"/api/projects/{pid}/timeline/redo").status_code == 200
    state = client.get(f"/api/projects/{pid}/timeline").json()
    clips = [c for t in state["tracks"] for c in t["clips"]]
    assert [c["id"] for c in clips] == [clip_id]
    assert state["can_undo"] is True and state["can_redo"] is False

    # a new mutation clears the redo stack
    client.post(f"/api/projects/{pid}/timeline/undo")
    res = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": 1, "timeline_start": 5.0, "source_in": 0.0, "source_out": 2.0},
    )
    assert res.status_code == 200
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert state["can_redo"] is False


def test_undo_empty_stack_409(client, project):
    pid = project
    assert client.post(f"/api/projects/{pid}/timeline/undo").status_code == 409
    assert client.post(f"/api/projects/{pid}/timeline/redo").status_code == 409


def test_failed_mutation_does_not_pollute_stack(client, project):
    pid = project
    state = client.get(f"/api/projects/{pid}/timeline").json()
    track_id = state["tracks"][0]["id"]
    # out-of-bounds source range -> 400, no undo step recorded
    res = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": 1, "timeline_start": 0.0, "source_in": 5.0, "source_out": 12.0},
    )
    assert res.status_code == 400
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert state["can_undo"] is False


def test_track_add_remove_undo(client, project):
    pid = project
    # first GET creates the two default tracks
    assert len(client.get(f"/api/projects/{pid}/timeline").json()["tracks"]) == 2
    res = client.post(f"/api/projects/{pid}/tracks")
    assert res.status_code == 200
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert len(state["tracks"]) == 3

    assert client.post(f"/api/projects/{pid}/timeline/undo").status_code == 200
    state = client.get(f"/api/projects/{pid}/timeline").json()
    assert len(state["tracks"]) == 2
    assert state["can_redo"] is True
