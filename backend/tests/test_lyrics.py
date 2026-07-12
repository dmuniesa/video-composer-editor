"""Lyrics service helpers + the transcription API flow (with a fake Whisper,
so tests don't need faster-whisper or a model download)."""
from __future__ import annotations

import shutil
import time

import pytest
from fastapi.testclient import TestClient

from app import settings
from app.main import app
from app.services import lyrics

SEGMENTS = [
    {"start": 10.0, "end": 13.0, "text": "hello sun"},
    {"start": 13.5, "end": 16.0, "text": "over the sea"},
    {"start": 30.0, "end": 33.0, "text": "chorus line"},
]


# ---- pure helpers ----

def test_vocal_ranges_merges_close_segments():
    ranges = lyrics.vocal_ranges(SEGMENTS, join_gap=2.0)
    assert ranges == [{"start": 10.0, "end": 16.0}, {"start": 30.0, "end": 33.0}]


def test_instrumental_ranges_are_the_gaps():
    vocals = lyrics.vocal_ranges(SEGMENTS)
    gaps = lyrics.instrumental_ranges(vocals, duration=40.0, min_gap=5.0)
    assert gaps == [
        {"start": 0.0, "end": 10.0},
        {"start": 16.0, "end": 30.0},
        {"start": 33.0, "end": 40.0},
    ]
    # a fully instrumental track is one big gap
    assert lyrics.instrumental_ranges([], 40.0, 5.0) == [{"start": 0.0, "end": 40.0}]


def test_vocal_ratio():
    vocals = [{"start": 10.0, "end": 16.0}]
    assert lyrics.vocal_ratio(10.0, 16.0, vocals) == 1.0
    assert lyrics.vocal_ratio(0.0, 10.0, vocals) == 0.0
    assert lyrics.vocal_ratio(10.0, 22.0, vocals) == 0.5
    assert lyrics.vocal_ratio(5.0, 5.0, vocals) == 0.0  # empty span


def test_attach_hints_annotates_sections():
    sections = [
        {"start": 0.0, "end": 10.0, "energy": 0.2},
        {"start": 10.0, "end": 20.0, "energy": 0.8},
    ]
    lyrics.attach_hints(sections, SEGMENTS)
    assert sections[0]["vocal_ratio"] == 0.0
    assert sections[0]["lyrics"] == ""
    assert sections[1]["vocal_ratio"] > 0.5
    assert sections[1]["lyrics"] == "hello sun / over the sea"


# ---- API flow ----

def wait_until(predicate, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.5)
    raise AssertionError("timed out waiting for background jobs")


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_transcription_flow(client, tmp_path, sample_song, monkeypatch):
    videos = tmp_path / "trip"
    videos.mkdir()
    shutil.copy(sample_song, videos / "song.wav")
    pid = client.post("/api/projects", json={"video_dir": str(videos)}).json()["id"]

    res = client.post(f"/api/projects/{pid}/song", json={"path": str(videos / "song.wav")})
    assert res.status_code == 200
    wait_until(lambda: client.get(f"/api/projects/{pid}/song").json()["status"] == "ready")

    # disabled in settings -> 409 pointing at Settings
    res = client.post(f"/api/projects/{pid}/song/lyrics")
    assert res.status_code == 409
    assert "Settings" in res.json()["detail"]

    s = settings.get()
    s.lyrics.enabled = True
    settings.save(s)

    # enabled but faster-whisper missing -> 409 with the install hint
    monkeypatch.setattr(lyrics, "available", lambda: False)
    res = client.post(f"/api/projects/{pid}/song/lyrics")
    assert res.status_code == 409
    assert "faster-whisper" in res.json()["detail"]

    # fake Whisper: the endpoint queues a job that stores the transcription
    monkeypatch.setattr(lyrics, "available", lambda: True)
    monkeypatch.setattr(
        lyrics, "transcribe", lambda path, model, language: {"language": "en", "segments": SEGMENTS}
    )
    res = client.post(f"/api/projects/{pid}/song/lyrics")
    assert res.status_code == 200

    def lyrics_ready():
        lyr = client.get(f"/api/projects/{pid}/song").json()["lyrics"]
        return lyr is not None and lyr["status"] in ("ready", "error")

    wait_until(lyrics_ready)
    song = client.get(f"/api/projects/{pid}/song").json()
    lyr = song["lyrics"]
    assert lyr["status"] == "ready", lyr["error"]
    assert lyr["language"] == "en"
    assert [l["text"] for l in lyr["segments"]] == ["hello sun", "over the sea", "chorus line"]
    assert lyr["vocal_ranges"] == [{"start": 10.0, "end": 16.0}, {"start": 30.0, "end": 33.0}]
    assert len(lyr["instrumental_ranges"]) >= 2
    # every section now reports how vocal it is
    assert all(s["vocal_ratio"] is not None for s in song["sections"])
