"""End-to-end API test over a real (generated) video + song, with the fake
agy CLI standing in for Gemini."""
from __future__ import annotations

import shutil
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    with TestClient(client_app()) as c:
        yield c


def client_app():
    return app


@pytest.fixture
def project(client, tmp_path, sample_video, sample_song, fake_agy):
    videos = tmp_path / "trip"
    videos.mkdir()
    shutil.copy(sample_video, videos / "beach.mp4")
    shutil.copy(sample_video, videos / "dinner.mp4")
    shutil.copy(sample_song, videos / "song.wav")

    res = client.post("/api/projects", json={"video_dir": str(videos)})
    assert res.status_code == 200, res.text
    return res.json()["id"], videos


def wait_until(predicate, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError("timed out waiting for background jobs")


def test_full_flow(client, project):
    pid, videos_dir = project

    # --- scan & media pipeline ---
    res = client.post(f"/api/projects/{pid}/scan")
    assert res.json()["added"] == 2

    def media_done():
        vs = client.get(f"/api/projects/{pid}/videos").json()
        return all(v["status"] in ("extracted", "ready", "error") for v in vs)

    wait_until(media_done)
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert len(videos) == 2
    v = videos[0]
    assert 7.5 < v["duration"] < 8.5
    assert v["fps"] == 25.0
    assert v["frame_count"] >= 3
    assert not v["has_proxy"]  # h264 plays natively

    # derived media is served
    assert client.get(f"/media/{pid}/thumb/{v['id']}").status_code == 200
    assert client.get(f"/media/{pid}/filmstrip/{v['id']}").status_code == 200
    ranged = client.get(f"/media/{pid}/video/{v['id']}", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert ranged.headers["content-range"].startswith("bytes 0-99/")

    # --- AI analysis through the fake agy ---
    res = client.post(f"/api/projects/{pid}/analyze", json={})
    assert res.status_code == 200

    def analyzed():
        vs = client.get(f"/api/projects/{pid}/videos").json()
        return all(v["status"] == "ready" for v in vs)

    wait_until(analyzed)
    v = client.get(f"/api/projects/{pid}/videos").json()[0]
    assert v["ai_score"] == 7
    assert "beach" in v["hashtags"]

    # --- rating + ranges ---
    ids = [x["id"] for x in client.get(f"/api/projects/{pid}/videos").json()]
    client.post(f"/api/projects/{pid}/videos/rating", json={"video_ids": ids, "stars": 4})
    client.post(f"/api/projects/{pid}/videos/rating", json={"video_ids": [ids[1]], "rejected": True})
    r = client.post(f"/api/projects/{pid}/videos/{ids[0]}/ranges", json={"t_in": 1.0, "t_out": 4.0})
    assert r.status_code == 200
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert videos[0]["stars"] == 4 and videos[0]["ranges"][0]["t_out"] == 4.0
    assert videos[1]["rejected"] is True

    # --- song analysis (librosa) + Gemini labels via fake agy ---
    res = client.post(f"/api/projects/{pid}/song", json={"path": str(videos_dir / "song.wav")})
    assert res.status_code == 200

    def song_ready():
        s = client.get(f"/api/projects/{pid}/song")
        return s.status_code == 200 and s.json()["status"] in ("ready", "error")

    wait_until(song_ready)
    song = client.get(f"/api/projects/{pid}/song").json()
    assert song["status"] == "ready", song["error"]
    assert song["bpm"] > 40
    assert len(song["sections"]) >= 1
    peaks = client.get(f"/api/projects/{pid}/song/peaks").json()
    assert len(peaks["peaks"]) > 100
    assert client.get(f"/media/{pid}/song").status_code == 200

    # --- timeline ---
    tl = client.get(f"/api/projects/{pid}/timeline").json()
    assert len(tl["tracks"]) == 2
    track_id = tl["tracks"][0]["id"]
    res = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": ids[0], "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.0},
    )
    assert res.status_code == 200
    overlap = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": ids[1], "timeline_start": 1.0, "source_in": 0.0, "source_out": 3.0},
    )
    assert overlap.status_code == 400

    # --- clip audio: per-video peaks + mute/volume controls ---
    vpeaks = client.get(f"/api/projects/{pid}/videos/{ids[0]}/audio-peaks")
    assert vpeaks.status_code == 200
    assert "peaks" in vpeaks.json()
    # mute the track's clip-audio lane and lower the song volume
    r = client.patch(f"/api/projects/{pid}/tracks/{track_id}/audio", json={"muted": True, "volume": 0.5})
    assert r.status_code == 200 and r.json()["audio_muted"] is True
    r = client.patch(f"/api/projects/{pid}/song/audio", json={"volume": 0.3})
    assert r.status_code == 200 and r.json()["volume"] == 0.3
    tl = client.get(f"/api/projects/{pid}/timeline").json()
    assert tl["tracks"][0]["audio_muted"] is True
    assert client.get(f"/api/projects/{pid}/song").json()["volume"] == 0.3

    # --- export ---
    res = client.get(f"/api/projects/{pid}/export.xml")
    assert res.status_code == 200
    root = ET.fromstring(res.text)
    assert root.tag == "xmeml"
    clipitem = root.find("sequence/media/video/track/clipitem")
    assert clipitem.findtext("name") == "beach.mp4"
    assert clipitem.findtext("in") == "25"  # 1s at 25fps
    pathurl = clipitem.findtext("file/pathurl")
    assert pathurl.startswith("file://localhost/") and pathurl.endswith("beach.mp4")
    # song included as audio (first stereo lane), and the muted clip-audio lane
    # is written disabled while the song carries its Audio Levels volume filter.
    audio_tracks = root.findall("sequence/media/audio/track")
    assert audio_tracks[0].find("clipitem") is not None  # song lane
    assert audio_tracks[0].findtext("clipitem/filter/effect/effectid") == "audiolevels"
    assert audio_tracks[2].findtext("enabled") == "FALSE"  # muted V1 clip-audio lane


def test_clear_analysis(client, project):
    """Settings 'Clear AI analysis' wipes description/score/hashtags from every
    video and leaves the clips re-analyzable, without re-running the AI itself."""
    pid, _videos_dir = project

    client.post(f"/api/projects/{pid}/scan")
    wait_until(
        lambda: all(
            v["status"] in ("extracted", "ready", "error")
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    client.post(f"/api/projects/{pid}/analyze", json={})
    wait_until(
        lambda: all(
            v["status"] == "ready"
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    before = client.get(f"/api/projects/{pid}/videos").json()
    assert len(before) == 2
    assert all(v["description"] and v["ai_score"] is not None and v["hashtags"] for v in before)

    r = client.post(f"/api/projects/{pid}/clear_analysis").json()
    assert r["cleared"] == 2
    assert "requeued" not in r  # clear does not re-run the AI

    after = client.get(f"/api/projects/{pid}/videos").json()
    assert all(v["description"] == "" and v["ai_score"] is None and v["hashtags"] == [] for v in after)
    assert all(v["status"] == "extracted" for v in after)

    # clips are still re-analyzable manually from the Library
    client.post(f"/api/projects/{pid}/analyze", json={})
    wait_until(
        lambda: all(
            v["status"] == "ready"
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    redone = client.get(f"/api/projects/{pid}/videos").json()
    assert all(v["description"] and v["ai_score"] is not None for v in redone)


def test_delete_video_from_project(client, project):
    """Removing a clip from the project drops its row, cache folder and any
    timeline clip using it, while leaving the source file and siblings intact."""
    from app import db as dbm

    pid, videos_dir = project

    client.post(f"/api/projects/{pid}/scan")
    wait_until(
        lambda: all(
            v["status"] in ("extracted", "ready", "error")
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert len(videos) == 2
    target = videos[0]
    other = videos[1]

    # place the target on the timeline so we can assert the clip is cleaned up
    track_id = client.get(f"/api/projects/{pid}/timeline").json()["tracks"][0]["id"]
    client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": target["id"], "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.0},
    )

    source_file = videos_dir / target["rel_path"]
    assert source_file.is_file()

    res = client.delete(f"/api/projects/{pid}/videos/{target['id']}")
    assert res.status_code == 200

    remaining = client.get(f"/api/projects/{pid}/videos").json()
    assert [v["id"] for v in remaining] == [other["id"]]
    # timeline clip referencing the deleted video is gone
    tracks = client.get(f"/api/projects/{pid}/timeline").json()["tracks"]
    assert all(c["video_id"] != target["id"] for t in tracks for c in t["clips"])
    # source file on disk is untouched
    assert source_file.is_file()

    # deleting again is a 404
    assert client.delete(f"/api/projects/{pid}/videos/{target['id']}").status_code == 404

    # the deletion is remembered: a rescan must NOT resurrect the file
    excluded = client.get(f"/api/projects/{pid}/excluded").json()
    assert [e["rel_path"] for e in excluded] == [target["rel_path"]]
    client.post(f"/api/projects/{pid}/scan")
    after = client.get(f"/api/projects/{pid}/videos").json()
    assert [v["id"] for v in after] == [other["id"]]

    # restoring the tombstone lets the next scan bring the file back
    assert client.delete(f"/api/projects/{pid}/excluded/{excluded[0]['id']}").status_code == 200
    assert client.get(f"/api/projects/{pid}/excluded").json() == []
    client.post(f"/api/projects/{pid}/scan")
    restored = client.get(f"/api/projects/{pid}/videos").json()
    assert {v["rel_path"] for v in restored} == {target["rel_path"], other["rel_path"]}


def test_compose_endpoint(client, project):
    """Auto-compose through the fake agy: queues a job, applies the model's
    actions, and marks the clips with the provider name."""
    from app import settings

    pid, _videos_dir = project

    client.post(f"/api/projects/{pid}/scan")
    wait_until(
        lambda: all(
            v["status"] in ("extracted", "ready", "error")
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )

    # default provider is mcp: composing in-app is rejected
    res = client.post(f"/api/projects/{pid}/compose", json={"instructions": "x"})
    assert res.status_code == 409
    assert "MCP" in res.json()["detail"]

    s = settings.get()
    s.composer.provider = "agy"
    settings.save(s)
    assert client.get(f"/api/projects/{pid}").json()["composer_provider"] == "agy"

    res = client.post(f"/api/projects/{pid}/compose", json={"instructions": "beach first"})
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    def compose_done():
        jobs_ = client.get(f"/api/projects/{pid}/jobs").json()
        job = next(j for j in jobs_ if j["id"] == job_id)
        return job["status"] in ("done", "error")

    wait_until(compose_done)
    job = next(j for j in client.get(f"/api/projects/{pid}/jobs").json() if j["id"] == job_id)
    assert job["status"] == "done", job["message"]

    tl = client.get(f"/api/projects/{pid}/timeline").json()
    clips = tl["tracks"][0]["clips"]
    # fake reply: video 1 placed ok, video 999 rejected (doesn't exist)
    assert len(clips) == 1
    assert clips[0]["placed_by"] == "agy"
    assert clips[0]["source_in"] == 1.0 and clips[0]["source_out"] == 4.0


def test_clip_speed_split_and_composition_fps(client, project):
    pid, _videos_dir = project

    # default composition settings + PATCH round-trip
    info = client.get(f"/api/projects/{pid}").json()
    assert info["composition_fps"] == 25.0
    assert (info["composition_width"], info["composition_height"]) == (1920, 1080)
    res = client.patch(f"/api/projects/{pid}", json={"composition_fps": 50, "composition_width": 1080, "composition_height": 1920})
    assert res.status_code == 200 and res.json()["composition_fps"] == 50.0
    assert (res.json()["composition_width"], res.json()["composition_height"]) == (1080, 1920)
    assert client.patch(f"/api/projects/{pid}", json={"composition_fps": 500}).status_code == 400
    assert client.patch(f"/api/projects/{pid}", json={"composition_width": 4}).status_code == 400

    # rename round-trip + validation
    res = client.patch(f"/api/projects/{pid}", json={"name": "  My Montage  "})
    assert res.status_code == 200 and res.json()["name"] == "My Montage"
    assert client.get(f"/api/projects/{pid}").json()["name"] == "My Montage"
    # the renamed project shows up with its new name in the home listing too
    listed = {p["id"]: p["name"] for p in client.get("/api/projects").json()}
    assert listed.get(pid) == "My Montage"
    assert client.patch(f"/api/projects/{pid}", json={"name": "   "}).status_code == 400

    client.post(f"/api/projects/{pid}/scan")
    wait_until(
        lambda: all(
            v["status"] in ("extracted", "ready", "error")
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    vid = client.get(f"/api/projects/{pid}/videos").json()[0]["id"]
    track_id = client.get(f"/api/projects/{pid}/timeline").json()["tracks"][0]["id"]

    # place at half speed: 3s of source occupies 6s of timeline
    res = client.post(
        f"/api/projects/{pid}/clips",
        json={"track_id": track_id, "video_id": vid, "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.0, "speed": 0.5},
    )
    assert res.status_code == 200
    cid = res.json()["id"]
    clip = client.get(f"/api/projects/{pid}/timeline").json()["tracks"][0]["clips"][0]
    assert clip["speed"] == 0.5 and clip["duration"] == 6.0

    # split at t=2 -> left keeps 1.0-2.0 of source, right starts at t=2
    res = client.post(f"/api/projects/{pid}/clips/{cid}/split", json={"at": 2.0})
    assert res.status_code == 200
    clips = client.get(f"/api/projects/{pid}/timeline").json()["tracks"][0]["clips"]
    assert len(clips) == 2
    assert clips[0]["source_out"] == 2.0
    assert clips[1]["timeline_start"] == 2.0 and clips[1]["speed"] == 0.5
    assert client.post(f"/api/projects/{pid}/clips/{cid}/split", json={"at": 99.0}).status_code == 400

    # PATCH speed and check the export carries sequence fps + time remap
    res = client.patch(f"/api/projects/{pid}/clips/{cid}", json={"speed": 1.0})
    assert res.status_code == 200
    root = ET.fromstring(client.get(f"/api/projects/{pid}/export.xml").text)
    assert root.findtext("sequence/rate/timebase") == "50"
    sc = root.find("sequence/media/video/format/samplecharacteristics")
    assert (sc.findtext("width"), sc.findtext("height")) == ("1080", "1920")
    items = root.findall("sequence/media/video/track/clipitem")
    effects = [i.findtext("filter/effect/effectid") for i in items]
    assert effects == [None, "timeremap"]  # first back at 1x, right half still 0.5x


def test_sources_add_remove_relink(client, tmp_path, sample_video):
    """Decoupled storage + multiple footage sources: add two folders (with a
    colliding rel_path), relink one that moved, then remove one."""
    storage = tmp_path / "project"
    storage.mkdir()
    dir_a = tmp_path / "cam_a"
    dir_b = tmp_path / "cam_b"
    dir_a.mkdir()
    dir_b.mkdir()
    # Same relative name in both sources — must not collide.
    shutil.copy(sample_video, dir_a / "clip.mp4")
    shutil.copy(sample_video, dir_b / "clip.mp4")

    # storage folder is separate from any footage -> starts with 0 sources
    res = client.post("/api/projects", json={"project_dir": str(storage)})
    assert res.status_code == 200, res.text
    pid = res.json()["id"]
    assert res.json()["sources"] == []

    # add both sources
    client.post(f"/api/projects/{pid}/sources", json={"path": str(dir_a)})
    info = client.post(f"/api/projects/{pid}/sources", json={"path": str(dir_b)}).json()
    assert len(info["sources"]) == 2
    # re-adding the same folder is rejected
    assert client.post(f"/api/projects/{pid}/sources", json={"path": str(dir_a)}).status_code == 409

    wait_until(
        lambda: len(client.get(f"/api/projects/{pid}/videos").json()) == 2
        and all(
            v["status"] in ("extracted", "ready", "error")
            for v in client.get(f"/api/projects/{pid}/videos").json()
        )
    )
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert {v["rel_path"] for v in videos} == {"clip.mp4"}  # colliding names coexist
    assert len({v["source_id"] for v in videos}) == 2
    for v in videos:
        assert client.get(f"/media/{pid}/video/{v['id']}").status_code in (200, 206)

    # relink source A to a moved location — video data is preserved
    a_id = next(s["id"] for s in info["sources"] if s["path"] == str(dir_a.resolve()))
    moved = tmp_path / "cam_a_moved"
    shutil.move(str(dir_a), str(moved))
    a_video = next(v for v in videos if v["source_id"] == a_id)
    res = client.patch(f"/api/projects/{pid}/sources/{a_id}", json={"path": str(moved)})
    assert res.status_code == 200
    # same video row (same id), still playable from the new path
    still = client.get(f"/api/projects/{pid}/videos").json()
    assert a_video["id"] in {v["id"] for v in still}
    assert client.get(f"/media/{pid}/video/{a_video['id']}").status_code in (200, 206)

    # remove source B — its videos disappear, source A intact
    b_id = next(s["id"] for s in info["sources"] if s["path"] == str(dir_b.resolve()))
    res = client.delete(f"/api/projects/{pid}/sources/{b_id}")
    assert res.status_code == 200
    assert len(res.json()["sources"]) == 1
    remaining = client.get(f"/api/projects/{pid}/videos").json()
    assert len(remaining) == 1 and remaining[0]["source_id"] == a_id


def test_import_project(client, tmp_path, sample_video):
    """A storage folder with an existing montage.db can be re-registered."""
    storage = tmp_path / "proj"
    storage.mkdir()
    footage = tmp_path / "clips"
    footage.mkdir()
    shutil.copy(sample_video, footage / "a.mp4")

    pid = client.post("/api/projects", json={"project_dir": str(storage)}).json()["id"]
    client.post(f"/api/projects/{pid}/sources", json={"path": str(footage)})

    # importing a folder with no project db fails
    empty = tmp_path / "empty"
    empty.mkdir()
    assert client.post("/api/projects/import", json={"project_dir": str(empty)}).status_code == 400

    # importing the real storage folder returns the same project
    res = client.post("/api/projects/import", json={"project_dir": str(storage)})
    assert res.status_code == 200
    assert res.json()["id"] == pid
    assert len(res.json()["sources"]) == 1


def test_fs_pick_native(client, monkeypatch):
    """The native picker endpoint returns the chosen path, or 501 (so the UI
    falls back to the in-app browser) when no native dialog is available."""
    from app.services import native_picker

    monkeypatch.setattr(native_picker, "available", lambda: True)
    monkeypatch.setattr(
        native_picker, "pick", lambda kind, initial="", title="": "/chosen/dir" if kind == "dir" else None
    )
    r = client.post("/api/fs/pick", json={"kind": "dir"})
    assert r.status_code == 200 and r.json()["path"] == "/chosen/dir"
    # cancelled dialog -> null path
    assert client.post("/api/fs/pick", json={"kind": "audio"}).json()["path"] is None

    monkeypatch.setattr(native_picker, "available", lambda: False)
    assert client.post("/api/fs/pick", json={"kind": "dir"}).status_code == 501


def test_fs_browser(client, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp3").touch()
    res = client.get(f"/api/fs/list?path={tmp_path}")
    data = res.json()
    assert "sub" in data["dirs"]
    assert "a.mp4" in data["videos"]
    assert "b.mp3" in data["audios"]
