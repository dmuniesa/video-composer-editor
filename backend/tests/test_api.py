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
    # song included as audio
    assert root.find("sequence/media/audio/track/clipitem") is not None


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


def test_fs_browser(client, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp3").touch()
    res = client.get(f"/api/fs/list?path={tmp_path}")
    data = res.json()
    assert "sub" in data["dirs"]
    assert "a.mp4" in data["videos"]
    assert "b.mp3" in data["audios"]
