import sqlite3

import pytest
from sqlalchemy import select

from app import db as dbm
from app.models import TimelineClip, Video
from app.services import timeline_ops as ops


@pytest.fixture
def db(tmp_path):
    session = dbm.open_session(tmp_path)
    session.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
    session.add(Video(rel_path="b.mp4", filename="b.mp4", duration=20.0, cache_key="k2"))
    session.commit()
    ops.ensure_default_tracks(session)
    session.commit()
    yield session
    session.close()


def place(db, video_id, track_index, start, s_in, s_out):
    """MCP-style placement addressing tracks by 0-based index."""
    return ops.place_clip(db, video_id, track_index, start, s_in, s_out, track_by_index=True)


def test_place_and_state(db):
    clip = place(db, 1, 0, 0.0, 1.0, 4.0)
    state = ops.timeline_state(db)
    assert state["tracks"][0]["clips"][0]["id"] == clip.id
    assert state["tracks"][0]["clips"][0]["duration"] == 3.0


def test_overlap_rejected(db):
    place(db, 1, 0, 0.0, 0.0, 5.0)
    with pytest.raises(ops.TimelineError, match="overlaps"):
        place(db, 2, 0, 3.0, 0.0, 5.0)
    # same range on the OTHER track is fine
    place(db, 2, 1, 3.0, 0.0, 5.0)
    # back-to-back placement is fine
    place(db, 2, 0, 5.0, 5.0, 8.0)


def test_source_bounds(db):
    with pytest.raises(ops.TimelineError, match="outside video duration"):
        place(db, 1, 0, 0.0, 5.0, 12.0)
    with pytest.raises(ops.TimelineError, match="greater than source_in"):
        place(db, 1, 0, 0.0, 5.0, 5.0)
    with pytest.raises(ops.TimelineError, match="not found"):
        place(db, 99, 0, 0.0, 0.0, 1.0)


def test_move_and_trim(db):
    clip = place(db, 1, 0, 0.0, 0.0, 5.0)
    other = place(db, 2, 0, 6.0, 0.0, 4.0)
    ops.update_clip(db, clip.id, timeline_start=1.0)
    with pytest.raises(ops.TimelineError, match="overlaps"):
        ops.update_clip(db, clip.id, timeline_start=3.0)
    # move to the second track instead (by index)
    ops.update_clip(db, clip.id, timeline_start=3.0, track_ref=1, track_by_index=True)
    state = ops.timeline_state(db)
    assert len(state["tracks"][0]["clips"]) == 1
    assert len(state["tracks"][1]["clips"]) == 1
    ops.remove_clip(db, other.id)
    assert ops.clear_track(db, 1, track_by_index=True) == 1


def test_track_id_resolution_via_api_semantics(db):
    """The REST API addresses tracks strictly by id."""
    tracks = ops.timeline_state(db)["tracks"]
    clip = ops.place_clip(db, 1, tracks[1]["id"], 0.0, 0.0, 2.0)
    assert clip.track_id == tracks[1]["id"]


def test_speed_scales_duration_and_overlap(db):
    ops.place_clip(db, 1, 0, 0.0, 0.0, 4.0, track_by_index=True, speed=0.5)
    c = ops.timeline_state(db)["tracks"][0]["clips"][0]
    assert c["speed"] == 0.5
    assert c["duration"] == 8.0  # 4s of source at half speed
    with pytest.raises(ops.TimelineError, match="overlaps"):
        place(db, 2, 0, 6.0, 0.0, 2.0)
    place(db, 2, 0, 8.0, 0.0, 2.0)


def test_speed_validation(db):
    with pytest.raises(ops.TimelineError, match="speed"):
        ops.place_clip(db, 1, 0, 0.0, 0.0, 4.0, track_by_index=True, speed=0.0)
    clip = place(db, 1, 0, 0.0, 0.0, 2.0)
    with pytest.raises(ops.TimelineError, match="speed"):
        ops.update_clip(db, clip.id, speed=30.0)


def test_update_speed_checks_overlap(db):
    a = place(db, 1, 0, 0.0, 0.0, 4.0)  # occupies 0-4
    place(db, 2, 0, 5.0, 0.0, 3.0)  # occupies 5-8
    with pytest.raises(ops.TimelineError, match="overlaps"):
        ops.update_clip(db, a.id, speed=0.5)  # would stretch to 0-8
    ops.update_clip(db, a.id, speed=2.0)  # shrinks to 0-2
    assert ops.timeline_state(db)["tracks"][0]["clips"][0]["duration"] == 2.0


def test_split_clip(db):
    clip = ops.place_clip(db, 1, 0, 0.0, 0.0, 4.0, track_by_index=True, speed=0.5)  # timeline 0-8
    right = ops.split_clip(db, clip.id, 3.0)
    assert clip.source_out == 1.5  # 3s of timeline * 0.5 speed
    assert right.source_in == 1.5
    assert right.source_out == 4.0
    assert right.timeline_start == 3.0
    assert right.speed == 0.5
    assert right.placed_by == clip.placed_by
    durs = [c["duration"] for c in ops.timeline_state(db)["tracks"][0]["clips"]]
    assert durs == [3.0, 5.0]


def test_split_bounds(db):
    clip = place(db, 1, 0, 1.0, 0.0, 4.0)
    with pytest.raises(ops.TimelineError, match="inside"):
        ops.split_clip(db, clip.id, 1.0)
    with pytest.raises(ops.TimelineError, match="inside"):
        ops.split_clip(db, clip.id, 5.0)
    with pytest.raises(ops.TimelineError, match="not found"):
        ops.split_clip(db, 999, 2.0)


def test_ensure_columns_migrates_old_db(tmp_path):
    """A pre-speed database opens cleanly: the missing columns are added with
    their defaults and old clips behave as 1x."""
    cache = tmp_path / dbm.CACHE_DIR_NAME
    cache.mkdir()
    con = sqlite3.connect(cache / "montage.db")
    con.execute(
        'CREATE TABLE track (id INTEGER PRIMARY KEY, "index" INTEGER, name VARCHAR)'
    )
    con.execute(
        """CREATE TABLE timeline_clip (
            id INTEGER PRIMARY KEY, track_id INTEGER, video_id INTEGER,
            timeline_start FLOAT, source_in FLOAT, source_out FLOAT,
            placed_by VARCHAR)"""
    )
    con.execute('INSERT INTO track (id, "index", name) VALUES (1, 0, \'V1\')')
    con.execute(
        "INSERT INTO timeline_clip (track_id, video_id, timeline_start, source_in, source_out, placed_by)"
        " VALUES (1, 1, 0.0, 0.0, 4.0, 'user')"
    )
    con.commit()
    con.close()

    session = dbm.open_session(tmp_path)
    clip = session.scalars(select(TimelineClip)).one()
    assert clip.speed == 1.0
    assert clip.duration == 4.0
    session.close()


def test_track_index_resolution(db):
    track3 = ops.add_track(db)
    assert track3.index == 2
    clip = place(db, 1, 2, 0.0, 0.0, 2.0)
    assert clip.track_id == track3.id
    ops.remove_track(db, track3.id)
    state = ops.timeline_state(db)
    assert [t["index"] for t in state["tracks"]] == [0, 1]
    # clip on the removed track is gone with it
    assert all(len(t["clips"]) == 0 for t in state["tracks"])
