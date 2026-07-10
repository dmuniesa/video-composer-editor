from pathlib import Path

import pytest

from app.services import gemini


def test_extract_json_from_fence():
    raw = 'Sure!\n```json\n{"a": 1}\n```\nDone.'
    assert gemini._extract_json(raw) == '{"a": 1}'


def test_extract_json_plain_with_nested_braces_and_strings():
    raw = 'prefix {"a": {"b": "close } brace"}, "c": [1, 2]} suffix'
    assert gemini._extract_json(raw) == '{"a": {"b": "close } brace"}, "c": [1, 2]}'


def test_extract_json_array():
    raw = 'labels: [{"index": 0, "label": "intro"}]'
    assert gemini._extract_json(raw) == '[{"index": 0, "label": "intro"}]'


def test_extract_json_missing():
    with pytest.raises(gemini.AgyError):
        gemini._extract_json("no json here")


def test_analyze_video_frames_with_fake_cli(fake_agy, tmp_path):
    frames = []
    for i in range(3):
        p = tmp_path / f"frame_{i:02d}.jpg"
        p.write_bytes(b"jpg")
        frames.append(p)
    result = gemini.analyze_video_frames(frames, workdir=tmp_path)
    assert result["score"] == 7
    assert "beach" in result["description"].lower()
    # hashtags are normalized: lowercased, stripped of # and spaces
    assert result["hashtags"] == ["beach", "sunny", "peoplewalking"]


def test_label_sections_with_fake_cli(fake_agy):
    sections = [
        {"start": 0, "end": 10, "energy": 0.4, "cluster": 0},
        {"start": 10, "end": 20, "energy": 0.6, "cluster": 1},
        {"start": 20, "end": 30, "energy": 1.0, "cluster": 2},
        {"start": 30, "end": 40, "energy": 0.3, "cluster": 0},
    ]
    labels = gemini.label_sections(40.0, 120.0, sections)
    assert labels == ["intro", "verse", "chorus", "outro"]


def test_agy_missing_binary(monkeypatch, tmp_path):
    monkeypatch.setenv("AGY_CMD", "definitely-not-a-real-binary --headless -p")
    p = tmp_path / "f.jpg"
    p.write_bytes(b"x")
    assert not gemini.agy_available()
    with pytest.raises(gemini.AgyError, match="not found"):
        gemini.analyze_video_frames([p], workdir=tmp_path)
