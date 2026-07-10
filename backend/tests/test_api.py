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


def test_fs_browser(client, tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.mp4").touch()
    (tmp_path / "b.mp3").touch()
    res = client.get(f"/api/fs/list?path={tmp_path}")
    data = res.json()
    assert "sub" in data["dirs"]
    assert "a.mp4" in data["videos"]
    assert "b.mp3" in data["audios"]
