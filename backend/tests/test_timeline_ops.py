import pytest

from app import db as dbm
from app.models import Video
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
