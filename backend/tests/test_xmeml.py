import os
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from app.services.xmeml import build_xmeml

GOLDEN = Path(__file__).parent / "golden_montage.xml"

VIDEOS = {
    1: {"path": "/media/trip/beach.mp4", "fps": 25.0, "width": 1920, "height": 1080, "duration": 12.0},
    2: {"path": "/media/trip/dinner with ñ.mov", "fps": 29.97, "width": 3840, "height": 2160, "duration": 30.0},
}
TRACKS = [
    {
        "name": "V1",
        "clips": [
            {"video_id": 1, "timeline_start": 0.0, "source_in": 2.0, "source_out": 6.0},
            {"video_id": 2, "timeline_start": 4.0, "source_in": 10.0, "source_out": 15.5},
        ],
    },
    {
        "name": "V2",
        "clips": [{"video_id": 1, "timeline_start": 8.0, "source_in": 0.0, "source_out": 3.0}],
    },
]
SONG = {"path": "/media/trip/song.mp3", "duration": 20.0}


def build() -> str:
    return build_xmeml("trip montage", VIDEOS, TRACKS, SONG)


@pytest.mark.skipif(
    os.name != "posix",
    reason="golden fixtures use POSIX paths; Path.resolve() rewrites them to "
    "drive paths (C:\\media\\...) elsewhere, so only the byte-for-byte compare "
    "is platform-bound — the structural tests still run everywhere",
)
def test_matches_golden_file():
    xml = build()
    if not GOLDEN.exists():  # pragma: no cover - first run generates it
        GOLDEN.write_text(xml)
    assert xml == GOLDEN.read_text()


def test_structure_and_frame_math():
    root = ET.fromstring(build())
    assert root.tag == "xmeml" and root.get("version") == "5"
    seq = root.find("sequence")
    assert seq.findtext("rate/timebase") == "25"

    video_tracks = seq.findall("media/video/track")
    assert len(video_tracks) == 2
    first = video_tracks[0].findall("clipitem")[0]
    # clip 1: starts at 0s -> frame 0, 4s long at 25fps -> end frame 100
    assert first.findtext("start") == "0"
    assert first.findtext("end") == "100"
    # source in 2s at 25fps
    assert first.findtext("in") == "50"
    assert first.findtext("out") == "150"

    # second clip on V1 uses the 29.97 source: in = 10s * 30 (ntsc timebase)
    second = video_tracks[0].findall("clipitem")[1]
    assert second.findtext("rate/timebase") == "30"
    assert second.findtext("rate/ntsc") == "TRUE"
    assert second.findtext("in") == "300"

    # file paths are percent-encoded file://localhost URLs
    pathurls = [e.text for e in root.iter("pathurl")]
    assert any(u.startswith("file://localhost/") and "%C3%B1" in u for u in pathurls)

    # stereo song = two audio tracks referencing one shared file id
    audio_tracks = seq.findall("media/audio/track")
    assert len(audio_tracks) == 2
    song_clip = audio_tracks[0].find("clipitem")
    assert song_clip.findtext("end") == "500"  # 20s * 25fps


def test_files_deduplicated():
    root = ET.fromstring(build())
    # video 1 appears in two clipitems but its <file> is defined once
    file_els = [e for e in root.iter("file")]
    defined = [e for e in file_els if e.find("pathurl") is not None]
    assert len(defined) == 3  # two videos + song


def test_no_song():
    xml = build_xmeml("no song", VIDEOS, TRACKS, None)
    root = ET.fromstring(xml)
    assert root.find("sequence/media/audio/track") is None


def test_sequence_fps_override():
    root = ET.fromstring(build_xmeml("t", VIDEOS, TRACKS, SONG, sequence_fps=50.0))
    seq = root.find("sequence")
    assert seq.findtext("rate/timebase") == "50"
    first = seq.findall("media/video/track")[0].findall("clipitem")[0]
    # clipitem keeps its source rate; timeline frames use the sequence rate
    assert first.findtext("rate/timebase") == "25"
    assert first.findtext("end") == "200"  # 4s at 50fps
    # no speed filter on 1x clips
    assert first.find("filter") is None


def test_clip_speed_time_remap():
    tracks = [
        {
            "name": "V1",
            "clips": [
                {"video_id": 1, "timeline_start": 0.0, "source_in": 2.0, "source_out": 6.0, "speed": 0.5},
            ],
        }
    ]
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, None, sequence_fps=25.0))
    item = root.find("sequence/media/video/track/clipitem")
    # 4s of source at 0.5x occupies 8s of timeline
    assert item.findtext("start") == "0"
    assert item.findtext("end") == "200"
    # in/out span the true source range at the source rate
    assert item.findtext("in") == "50"
    assert item.findtext("out") == "150"
    effect = item.find("filter/effect")
    assert effect is not None
    assert effect.findtext("effectid") == "timeremap"
    params = {p.findtext("parameterid"): p.findtext("value") for p in effect.findall("parameter")}
    assert params["speed"] == "50.0"  # 0.5x -> 50%
    assert params["variablespeed"] == "0"
    assert params["reverse"] == "FALSE"
