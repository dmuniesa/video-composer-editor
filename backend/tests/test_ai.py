import json

import httpx
import pytest

from app import settings
from app.services import ai, gemini, openai_client


# ---- JSON extraction ----

def test_extract_json_from_fence():
    raw = 'Sure!\n```json\n{"a": 1}\n```\nDone.'
    assert ai._extract_json(raw) == '{"a": 1}'


def test_extract_json_plain_with_nested_braces_and_strings():
    raw = 'prefix {"a": {"b": "close } brace"}, "c": [1, 2]} suffix'
    assert ai._extract_json(raw) == '{"a": {"b": "close } brace"}, "c": [1, 2]}'


def test_extract_json_array():
    raw = 'labels: [{"index": 0, "label": "intro"}]'
    assert ai._extract_json(raw) == '[{"index": 0, "label": "intro"}]'


def test_extract_json_missing():
    with pytest.raises(ai.AIError):
        ai._extract_json("no json here")


# ---- agy provider ----

def test_analyze_clip_with_fake_cli(fake_agy, tmp_path):
    frames = []
    for i in range(3):
        p = tmp_path / f"frame_{i:02d}.jpg"
        p.write_bytes(b"jpg")
        frames.append(p)
    assert ai.provider() == "agy"
    result = ai.analyze_clip(frames, workdir=tmp_path)
    assert result["score"] == 7
    assert "beach" in result["description"].lower()
    # hashtags are normalized: lowercased, stripped of # and spaces
    assert result["hashtags"] == ["beach", "sunny", "peoplewalking"]
    # frames mode never asks for (or keeps) highlights, even if the model
    # volunteers them — timestamps can't be judged from stills
    assert result["highlights"] == []


def test_analyze_clip_video_mode_returns_highlight_ranges(fake_agy, tmp_path):
    clip = tmp_path / "preview.mp4"
    clip.write_bytes(b"mp4")
    result = ai.analyze_clip([], workdir=tmp_path, video_file=clip, duration=10.0)
    assert result["score"] == 7
    # the fake returns {start_s: 0.5, end_s: 2.0} -> normalized to t_in/t_out
    assert result["highlights"] == [{"t_in": 0.5, "t_out": 2.0, "reason": "best moment"}]


def test_norm_highlight_ranges():
    norm = ai._norm_highlight_ranges
    # clamps to [0, duration], drops sub-0.5s and invalid items, sorts, caps at 3
    raw = [
        {"start_s": 8, "end_s": 99, "reason": "clamped end"},
        {"start_s": -2, "end_s": 1.0, "reason": "clamped start"},
        {"start_s": 3, "end_s": 3.2, "reason": "too short"},
        {"start_s": "x", "end_s": 5, "reason": "not numeric"},
        "not a dict",
        {"start_s": 4, "end_s": 6, "reason": "r" * 500},
        {"start_s": 2, "end_s": 3, "reason": "ok"},
    ]
    out = norm(raw, 10.0)
    assert [h["t_in"] for h in out] == [0.0, 2.0, 4.0]  # sorted, capped at 3
    assert out[0] == {"t_in": 0.0, "t_out": 1.0, "reason": "clamped start"}
    assert out[2]["reason"] == "r" * 200
    # garbage inputs never raise
    assert norm(None, 10.0) == []
    assert norm({"start_s": 1}, 10.0) == []
    assert norm([{"start_s": 1, "end_s": 5}], 0.0) == []


def test_label_sections_with_fake_cli(fake_agy):
    sections = [
        {"start": 0, "end": 10, "energy": 0.4, "cluster": 0},
        {"start": 10, "end": 20, "energy": 0.6, "cluster": 1},
        {"start": 20, "end": 30, "energy": 1.0, "cluster": 2},
        {"start": 30, "end": 40, "energy": 0.3, "cluster": 0},
    ]
    labels = ai.label_sections(40.0, 120.0, sections)
    assert labels == ["intro", "verse", "chorus", "outro"]


def test_label_sections_includes_lyric_hints(monkeypatch):
    """When sections carry Whisper hints, the prompt shows vocals% + lyrics
    and the explanatory note; without hints the prompt stays as before."""
    prompts = []

    def fake_ask(prompt, images, workdir):
        prompts.append(prompt)
        return '[{"index": 0, "label": "instrumental"}, {"index": 1, "label": "verse"}]'

    monkeypatch.setattr(ai, "_ask", fake_ask)
    sections = [
        {"start": 0, "end": 10, "energy": 0.4, "cluster": 0, "vocal_ratio": 0.0, "lyrics": ""},
        {"start": 10, "end": 20, "energy": 0.8, "cluster": 1, "vocal_ratio": 0.72, "lyrics": "hello sun"},
    ]
    labels = ai.label_sections(20.0, 120.0, sections)
    assert labels == ["instrumental", "verse"]
    assert "vocals=0%" in prompts[0]
    assert 'vocals=72% lyrics="hello sun"' in prompts[0]
    assert "zero vocals are instrumental" in prompts[0]

    ai.label_sections(20.0, 120.0, [{"start": 0, "end": 20, "energy": 1.0, "cluster": 0}])
    assert "vocals=" not in prompts[1]
    assert "zero vocals" not in prompts[1]


def test_agy_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("AGY_CMD", "definitely-not-a-real-binary --headless -p")
    assert not gemini.agy_available()
    assert ai.provider() is None  # nothing else configured
    p = tmp_path / "f.jpg"
    p.write_bytes(b"x")
    with pytest.raises(ai.AIError, match="No AI provider"):
        ai.analyze_clip([p], workdir=tmp_path)


# ---- OpenAI-compatible provider ----

def _openai_settings():
    s = settings.get()
    s.ai.provider = "openai"
    s.ai.openai_base_url = "https://fake.example/v1"
    s.ai.openai_api_key = "test-key"
    s.ai.openai_model = "glm-4.6v-flash"
    settings.save(s)


def test_openai_chat_sends_images_and_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_CMD", "definitely-not-a-real-binary -p")
    _openai_settings()

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"pong": true}'}}]},
        )

    img = tmp_path / "f.jpg"
    img.write_bytes(b"\xff\xd8jpegdata")
    text = openai_client.chat("hello", images=[img], transport=httpx.MockTransport(handler))

    assert text == '{"pong": true}'
    assert captured["url"] == "https://fake.example/v1/chat/completions"
    assert captured["auth"] == "Bearer test-key"
    body = captured["body"]
    assert body["model"] == "glm-4.6v-flash"
    parts = body["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "hello"}
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_openai_error_status(monkeypatch):
    _openai_settings()
    transport = httpx.MockTransport(lambda req: httpx.Response(401, text="bad key"))
    with pytest.raises(openai_client.OpenAIError, match="401"):
        openai_client.chat("hi", transport=transport)


def test_dispatcher_uses_openai_when_agy_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_CMD", "definitely-not-a-real-binary -p")
    _openai_settings()
    assert ai.provider() == "openai"

    def fake_chat(prompt, images=None, transport=None):
        assert "attached images" in prompt
        assert len(images) == 2
        return '{"description": "GLM saw a lake.", "score": 8, "hashtags": ["Lake", "boat trip"]}'

    monkeypatch.setattr(openai_client, "chat", fake_chat)
    frames = []
    for i in range(2):
        p = tmp_path / f"frame_{i:02d}.jpg"
        p.write_bytes(b"x")
        frames.append(p)
    result = ai.analyze_clip(frames, workdir=tmp_path)
    assert result["score"] == 8
    assert result["hashtags"] == ["lake", "boattrip"]


def test_provider_off(fake_agy):
    s = settings.get()
    s.ai.provider = "off"
    settings.save(s)
    assert ai.provider() is None
    assert not ai.available()


# ---- settings persistence + frame settings ----

def test_settings_roundtrip_and_frame_count():
    from app.services import frames

    s = settings.get()
    s.frames.min_count = 4
    s.frames.max_count = 6
    s.frames.seconds_per_frame = 10
    settings.save(s)
    settings.reload()

    assert settings.get().frames.min_count == 4
    assert frames.frame_count_for(0) == 4
    assert frames.frame_count_for(25) == 6  # 4 + 25//10 = 6
    assert frames.frame_count_for(500) == 6  # capped at max


def test_settings_api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        res = client.get("/api/settings")
        assert res.status_code == 200
        data = res.json()
        assert data["frames"]["min_count"] == 3
        assert "ai_status" in data

        data["frames"]["min_count"] = 5
        data["ai"]["provider"] = "openai"
        data["ai"]["openai_base_url"] = "https://api.z.ai/api/paas/v4"
        data["ai"]["openai_model"] = "glm-4.6v-flash"
        data.pop("ai_status")
        res = client.put("/api/settings", json=data)
        assert res.status_code == 200
        assert res.json()["frames"]["min_count"] == 5
        # provider resolves to openai now that base URL + model are set
        assert res.json()["ai_status"]["provider"] == "openai"

        res = client.put("/api/settings", json={"frames": {"min_count": 0}})
        assert res.status_code == 422  # validation
