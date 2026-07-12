from xml.etree import ElementTree as ET

from app.services.fcpxml import build_fcpxml

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
    return build_fcpxml("trip montage", VIDEOS, TRACKS, SONG)


def _rational_seconds(value: str) -> float:
    assert value.endswith("s")
    body = value[:-1]
    if "/" in body:
        num, den = body.split("/")
        return int(num) / int(den)
    return float(body)


def test_structure():
    root = ET.fromstring(build())
    assert root.tag == "fcpxml"
    assert root.get("version") == "1.9"

    fmt = root.find("./resources/format")
    # dominant fps is 25 (two clips of video 1 vs one of video 2)
    assert fmt.get("frameDuration") == "1/25s"
    assert (fmt.get("width"), fmt.get("height")) == ("1920", "1080")

    assets = root.findall("./resources/asset")
    assert len(assets) == 3  # two videos + song
    reps = [a.find("media-rep") for a in assets]
    assert all(r is not None and r.get("src").startswith("file://") for r in reps)
    # non-ASCII path is percent-encoded into a valid URL
    assert any("%C3%B1" in r.get("src") for r in reps)

    song_asset = next(a for a in assets if a.get("id") == "r-song")
    assert song_asset.get("hasAudio") == "1"
    assert _rational_seconds(song_asset.get("duration")) == 20.0


def test_lanes_and_times():
    root = ET.fromstring(build())
    gap = root.find(".//spine/gap")
    # the gap spans the whole montage: song is the longest element (20 s)
    assert _rational_seconds(gap.get("duration")) == 20.0

    clips = gap.findall("asset-clip")
    song_clips = [c for c in clips if c.get("lane") == "-1"]
    assert len(song_clips) == 1
    assert song_clips[0].get("ref") == "r-song"

    lane1 = [c for c in clips if c.get("lane") == "1"]
    lane2 = [c for c in clips if c.get("lane") == "2"]
    assert len(lane1) == 2 and len(lane2) == 1

    first = lane1[0]
    assert _rational_seconds(first.get("offset")) == 0.0
    assert _rational_seconds(first.get("start")) == 2.0
    assert _rational_seconds(first.get("duration")) == 4.0

    second = lane1[1]
    assert _rational_seconds(second.get("offset")) == 4.0
    # 5.5 s is not a whole number of frames at 25 fps: the edit snaps to the
    # sequence rate (9.5 s end -> frame 238), like the xmeml exporter does
    assert _rational_seconds(second.get("duration")) == 5.52

    overlay = lane2[0]
    assert _rational_seconds(overlay.get("offset")) == 8.0
    assert _rational_seconds(overlay.get("duration")) == 3.0


def test_no_song():
    root = ET.fromstring(build_fcpxml("no song", VIDEOS, TRACKS, None))
    assert root.find("./resources/asset[@id='r-song']") is None
    gap = root.find(".//spine/gap")
    # gap now ends with the last clip (track V2 clip ends at 11 s)
    assert _rational_seconds(gap.get("duration")) == 11.0
    assert all(c.get("lane") != "-1" for c in gap.findall("asset-clip"))
