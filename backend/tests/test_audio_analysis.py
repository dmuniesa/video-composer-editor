import json

from app.services import audio_analysis


def test_analyze_synthetic_track(sample_song):
    result = audio_analysis.analyze(sample_song)
    assert 29.0 < result.duration < 31.0
    # The click track is 120 BPM; librosa may lock onto a harmonic.
    assert result.bpm > 40
    assert len(result.beats) > 10
    assert all(0 <= b <= result.duration for b in result.beats)

    assert len(result.sections) >= 1
    assert result.sections[0]["start"] == 0.0
    assert abs(result.sections[-1]["end"] - result.duration) < 0.1
    # contiguous, no gaps
    for a, b in zip(result.sections[:-1], result.sections[1:]):
        assert a["end"] == b["start"]
    for s in result.sections:
        assert 0.0 <= s["energy"] <= 1.0
        assert "cluster" in s


def test_peaks(sample_song, tmp_path):
    dest = tmp_path / "peaks.json"
    audio_analysis.compute_peaks(sample_song, dest, buckets=500)
    data = json.loads(dest.read_text())
    assert len(data["peaks"]) == 500
    assert all(lo <= hi for lo, hi in data["peaks"])
