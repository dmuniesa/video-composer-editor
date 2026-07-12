"""Auto-compose: settings, prompt context, action parsing/application, and
the provider dispatch (fake agy CLI / patched OpenAI client)."""
from __future__ import annotations

import json

import pytest

from app import db as dbm
from app import settings
from app.models import Song, SongSection, Video, VideoRating
from app.services import composer, openai_client
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


def _composer_settings(provider: str, **ai_fields) -> None:
    s = settings.get()
    s.composer.provider = provider
    for key, value in ai_fields.items():
        setattr(s.ai, key, value)
    settings.save(s)


# ---- settings ----

def test_composer_settings_default_and_roundtrip():
    assert settings.get().composer.provider == "mcp"
    _composer_settings("agy")
    settings.reload()
    assert settings.get().composer.provider == "agy"


def test_composer_settings_missing_key_defaults(tmp_path, monkeypatch):
    # A settings.json from before the composer existed still loads.
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"ai": {"provider": "off"}}))
    monkeypatch.setenv("MONTAGE_SETTINGS", str(legacy))
    s = settings.reload()
    assert s.composer.provider == "mcp"
    assert s.ai.provider == "off"


def test_composer_availability(monkeypatch):
    assert settings.get().composer.provider == "mcp"
    assert not composer.available()  # mcp composes externally
    monkeypatch.setenv("AGY_CMD", "definitely-not-a-real-binary -p")
    _composer_settings("agy")
    assert not composer.available()
    assert "agy" in composer.unavailable_reason()
    _composer_settings("openai", openai_base_url="https://fake.example/v1", openai_model="glm-4.7")
    assert composer.available()


# ---- parse_actions ----

def test_parse_actions_plain_and_fenced():
    raw = '{"summary": "s", "actions": [{"action": "remove", "clip_id": 1}]}'
    actions, summary = composer.parse_actions(raw)
    assert summary == "s" and actions[0]["action"] == "remove"
    fenced = f"Sure!\n```json\n{raw}\n```"
    actions, _ = composer.parse_actions(fenced)
    assert len(actions) == 1


def test_parse_actions_rejects_bad_shapes():
    with pytest.raises(Exception):
        composer.parse_actions("no json at all")
    with pytest.raises(composer.ComposeError, match="actions"):
        composer.parse_actions('{"summary": "no actions"}')
    with pytest.raises(composer.ComposeError, match="invalid"):
        composer.parse_actions('{"actions": [{"action": "explode"}]}')
    too_many = json.dumps({"actions": [{"action": "remove", "clip_id": 1}] * 301})
    with pytest.raises(composer.ComposeError, match="too many"):
        composer.parse_actions(too_many)


# ---- apply_actions ----

def test_apply_actions_collects_errors_and_continues(db):
    actions = [
        {"action": "place", "video_id": 1, "track": 0, "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.0},
        # overlaps the first placement -> rejected, but the rest still applies
        {"action": "place", "video_id": 2, "track": 0, "timeline_start": 2.0, "source_in": 0.0, "source_out": 3.0},
        {"action": "place", "video_id": 2, "track": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 5.0},
    ]
    applied, errors = composer.apply_actions(db, actions, placed_by="agy")
    assert applied == 2
    assert len(errors) == 1 and "overlaps" in errors[0]
    state = ops.timeline_state(db)
    assert [c["placed_by"] for c in state["tracks"][0]["clips"]] == ["agy"]
    assert len(state["tracks"][1]["clips"]) == 1


def test_apply_actions_move_remove_clear(db):
    clip = ops.place_clip(db, 1, 0, 0.0, 0.0, 4.0, track_by_index=True)
    other = ops.place_clip(db, 2, 0, 6.0, 0.0, 4.0, track_by_index=True)
    actions = [
        {"action": "move", "clip_id": clip.id, "timeline_start": 1.0},  # partial move
        {"action": "remove", "clip_id": other.id},
        {"action": "remove", "clip_id": 12345},  # unknown -> error
        {"action": "clear_track", "track": 0},
    ]
    applied, errors = composer.apply_actions(db, actions, placed_by="openai")
    assert applied == 3
    assert len(errors) == 1 and "not found" in errors[0]
    assert ops.timeline_state(db)["tracks"][0]["clips"] == []


def test_apply_actions_missing_field(db):
    applied, errors = composer.apply_actions(db, [{"action": "place", "video_id": 1}], "agy")
    assert applied == 0 and len(errors) == 1


# ---- build_context ----

def test_build_context(db):
    db.add(VideoRating(video_id=1, stars=4))
    db.add(VideoRating(video_id=2, rejected=True))
    song = Song(
        path="song.wav",
        duration=30.0,
        bpm=120.0,
        beats_json=json.dumps([i * 0.5 for i in range(60)]),
        downbeats_json=json.dumps([i * 2.0 for i in range(15)]),
        status="ready",
    )
    db.add(song)
    db.flush()
    db.add(SongSection(song_id=song.id, start=0.0, end=15.0, label="intro", energy=0.4))
    db.commit()

    ctx = composer.build_context(db)
    assert [v["id"] for v in ctx["videos"]] == [1]  # rejected excluded
    assert ctx["videos"][0]["stars"] == 4
    assert ctx["song"]["bpm"] == 120.0
    assert len(ctx["song"]["beats"]) == 60
    assert ctx["song"]["sections"][0]["label"] == "intro"
    assert ctx["timeline"]["tracks"][0]["clips"] == []


def test_build_context_omits_huge_beat_lists(db):
    song = Song(
        path="song.wav",
        duration=600.0,
        bpm=120.0,
        beats_json=json.dumps([i * 0.5 for i in range(1200)]),
        downbeats_json=json.dumps([i * 2.0 for i in range(300)]),
        status="ready",
    )
    db.add(song)
    db.commit()
    ctx = composer.build_context(db)
    assert "beats" not in ctx["song"]
    assert "1200 beats omitted" in ctx["song"]["beats_note"]
    assert len(ctx["song"]["downbeats"]) == 300


# ---- provider dispatch (service level) ----

def _fake_job():
    from app.services import jobs

    return jobs.Job(id=0, pid="test", kind="compose", label="compose")


def test_run_compose_with_fake_agy(fake_agy, tmp_path):
    with dbm.open_session(tmp_path) as db:
        db.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
        db.commit()
        ops.ensure_default_tracks(db)
        db.commit()
    _composer_settings("agy")
    pid = dbm.register_project(tmp_path)

    result = composer.run_compose(pid, tmp_path, "beach first", _fake_job())
    assert result["provider"] == "agy"
    assert result["applied"] == 1  # fake reply places video 1 ok, video 999 fails
    assert result["actions_total"] == 2
    assert len(result["errors"]) == 1 and "not found" in result["errors"][0]
    assert "beach" in result["summary"].lower()

    with dbm.open_session(tmp_path) as db:
        state = ops.timeline_state(db)
        clip = state["tracks"][0]["clips"][0]
        assert clip["placed_by"] == "agy"
        assert clip["source_in"] == 1.0 and clip["source_out"] == 4.0


def test_run_compose_with_openai(tmp_path, monkeypatch):
    with dbm.open_session(tmp_path) as db:
        db.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
        db.commit()
        ops.ensure_default_tracks(db)
        db.commit()
    _composer_settings("openai", openai_base_url="https://fake.example/v1", openai_model="glm-4.7")
    pid = dbm.register_project(tmp_path)

    def fake_chat(prompt, images=None, transport=None):
        assert "composing a video montage" in prompt
        assert "make it dreamy" in prompt
        assert '"a.mp4"' in prompt  # context made it into the prompt
        return (
            '{"summary": "done", "actions": [{"action": "place", "video_id": 1, '
            '"track": 0, "timeline_start": 0.0, "source_in": 0.0, "source_out": 3.0}]}'
        )

    monkeypatch.setattr(openai_client, "chat", fake_chat)
    result = composer.run_compose(pid, tmp_path, "make it dreamy", _fake_job())
    assert result == {
        "provider": "openai",
        "applied": 1,
        "errors": [],
        "summary": "done",
        "actions_total": 1,
    }
    with dbm.open_session(tmp_path) as db:
        assert ops.timeline_state(db)["tracks"][0]["clips"][0]["placed_by"] == "openai"


def test_run_compose_retries_then_fails_on_garbage(tmp_path, monkeypatch):
    with dbm.open_session(tmp_path) as db:
        db.add(Video(rel_path="a.mp4", filename="a.mp4", duration=10.0, cache_key="k1"))
        db.commit()
    _composer_settings("openai", openai_base_url="https://fake.example/v1", openai_model="glm-4.7")
    pid = dbm.register_project(tmp_path)

    calls = {"n": 0}

    def bad_chat(prompt, images=None, transport=None):
        calls["n"] += 1
        return "I refuse to answer in JSON."

    monkeypatch.setattr(openai_client, "chat", bad_chat)
    with pytest.raises(composer.ComposeError, match="could not parse"):
        composer.run_compose(pid, tmp_path, "", _fake_job())
    assert calls["n"] == 2


# ---- settings API validation ----

def test_settings_api_composer_field():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        data = client.get("/api/settings").json()
        assert data["composer"]["provider"] == "mcp"

        data["composer"]["provider"] = "agy"
        data.pop("ai_status")
        res = client.put("/api/settings", json=data)
        assert res.status_code == 200
        assert res.json()["composer"]["provider"] == "agy"

        data["composer"]["provider"] = "banana"
        res = client.put("/api/settings", json=data)
        assert res.status_code == 422
