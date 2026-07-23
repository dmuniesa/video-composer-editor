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
    os.name != "nt",
    reason="UNC path handling is Windows-specific — Path.resolve keeps the "
    "\\\\host\\\\share authority only on Windows",
)
def test_unc_path_url_uses_authority_not_localhost():
    # NAS media registered by its UNC path (\\host\share\...) must export with
    # the host as the file:// authority, not under 'localhost' — otherwise
    # Premiere treats the host as a local folder name and the media is missing.
    from app.services import xmeml

    unc = r"\\nas-server\Public\bioparc\DSCF9102.MOV"
    assert xmeml._pathurl(unc) == "file://nas-server/Public/bioparc/DSCF9102.MOV"
    # local drive paths keep their existing localhost/<drive> form
    assert xmeml._pathurl(r"C:\media\beach.mp4").startswith("file://localhost/")


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

    # audio layout: the song's stereo track first, then one stereo track per
    # video track for the clip audio. Each stereo track is two "exploded" mono
    # tracks, so 3 stereo tracks -> 6 <track> elements.
    assert root.find("sequence").get("explodedTracks") == "true"
    audio_tracks = seq.findall("media/audio/track")
    assert len(audio_tracks) == 6  # (song + V1 + V2) x 2 exploded channels
    assert all(t.get("premiereTrackType") == "Stereo" for t in audio_tracks)

    # the song sits on the first (top) stereo track
    song_clip = audio_tracks[0].find("clipitem")
    assert song_clip.findtext("name") == "song.mp3"
    assert song_clip.get("premiereChannelType") == "stereo"
    assert song_clip.findtext("end") == "500"  # 20s * 25fps
    assert song_clip.findtext("sourcetrack/trackindex") == "1"
    assert song_clip.findtext("file/media/audio/channelcount") == "2"

    # V1's two clips' audio ride the next stereo track (exploded tracks 3 & 4)
    v1_audio = audio_tracks[2].findall("clipitem")
    assert len(v1_audio) == 2
    assert v1_audio[0].findtext("sourcetrack/trackindex") == "1"
    # placed in sequence-rate frames matching the video clip's footprint
    assert v1_audio[0].findtext("start") == "0"
    assert v1_audio[0].findtext("end") == "100"

    # each video clip links down to its two audio channels
    audio_links = [
        l for l in first.findall("link") if l.findtext("mediatype") == "audio"
    ]
    assert [l.findtext("linkclipref") for l in audio_links] == [
        "audioclip-1-1",
        "audioclip-1-2",
    ]

    # one 2-channel stereo output made of two mono groups
    assert seq.findtext("media/audio/numOutputChannels") == "2"
    groups = seq.findall("media/audio/outputs/group")
    assert [g.findtext("numchannels") for g in groups] == ["1", "1"]


def test_files_deduplicated():
    root = ET.fromstring(build())
    # video 1 appears in two clipitems but its <file> is defined once
    file_els = [e for e in root.iter("file")]
    defined = [e for e in file_els if e.find("pathurl") is not None]
    assert len(defined) == 3  # two videos + song


def test_no_song():
    xml = build_xmeml("no song", VIDEOS, TRACKS, None)
    root = ET.fromstring(xml)
    seq = root.find("sequence")
    # no song, but each video track still lays its clip audio on its own stereo
    # track: V1 + V2 -> two stereo tracks -> four exploded <track> elements
    audio_tracks = seq.findall("media/audio/track")
    assert len(audio_tracks) == 4
    names = {c.findtext("name") for c in seq.findall("media/audio/track/clipitem")}
    assert "song.mp3" not in names
    # with no song on top, the first audio track belongs to V1's first clip
    assert seq.find("media/audio/track/clipitem").findtext("name") == "beach.mp4"


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


def test_mixed_fps_1x_clip_out_uses_clip_rate():
    # Sequence runs faster than the source (50fps seq vs 25fps source). The clip's
    # <out> must be computed in the CLIP's rate, not the sequence rate, otherwise
    # the out point overshoots the media and the clip shows black in Premiere.
    tracks = [
        {
            "name": "V1",
            "clips": [
                # 4s of a 5s source, placed at the timeline start
                {"video_id": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 4.0},
            ],
        }
    ]
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, None, sequence_fps=50.0))
    item = root.find("sequence/media/video/track/clipitem")
    assert item.findtext("rate/timebase") == "25"   # clip keeps its source rate
    assert item.findtext("start") == "0"
    assert item.findtext("end") == "200"            # 4s at the 50fps sequence
    assert item.findtext("in") == "0"
    # out = in + slot(converted to clip rate) = 0 + round(200 * 25/50) = 100
    # i.e. 4.0s of source — NOT 200 frames (8s), which would blow past the media.
    assert item.findtext("out") == "100"
    media_end = float(item.findtext("duration"))  # 12s * 25fps = 300 frames
    assert float(item.findtext("out")) <= media_end


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


def test_audio_mute_and_volume():
    tracks = [
        {
            "name": "V1",
            "audio_muted": True,
            "audio_volume": 1.0,
            "clips": [
                {"video_id": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 4.0}
            ],
        }
    ]
    song = {"path": "/media/trip/song.mp3", "duration": 20.0, "muted": False, "volume": 0.5}
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, song))
    audio_tracks = root.findall("sequence/media/audio/track")

    # tracks 1-2 = song: not muted (enabled) but volume 0.5 -> Audio Levels filter
    assert audio_tracks[0].findtext("enabled") == "TRUE"
    song_clip = audio_tracks[0].find("clipitem")
    assert song_clip.findtext("filter/effect/effectid") == "audiolevels"
    assert song_clip.findtext("filter/effect/parameter/value") == "0.5"

    # tracks 3-4 = V1 clip audio: muted -> track disabled, full volume -> no filter
    assert audio_tracks[2].findtext("enabled") == "FALSE"
    assert audio_tracks[2].find("clipitem/filter") is None


def test_clip_audio_gain_normalize_on():
    # final db = norm(-3) + user(-6) = -9; level = 1.0 * 10^(-9/20)
    tracks = [
        {
            "name": "V1", "audio_muted": False, "audio_volume": 1.0,
            "clips": [
                {"video_id": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 4.0,
                 "audio_gain_db": -6.0, "norm_gain_db": -3.0},
            ],
        }
    ]
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, None, normalize_audio=True))
    clip = root.find("sequence/media/audio/track/clipitem")
    val = float(clip.findtext("filter/effect/parameter/value"))
    assert abs(val - 10 ** (-9 / 20)) < 1e-3
    assert clip.findtext("filter/effect/effectid") == "audiolevels"


def test_clip_audio_gain_normalize_off_ignores_norm_gain():
    tracks = [
        {
            "name": "V1", "audio_muted": False, "audio_volume": 1.0,
            "clips": [
                {"video_id": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 4.0,
                 "audio_gain_db": 6.0, "norm_gain_db": -20.0},
            ],
        }
    ]
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, None, normalize_audio=False))
    clip = root.find("sequence/media/audio/track/clipitem")
    # only the +6 dB user offset applies; norm_gain_db is ignored when off
    val = float(clip.findtext("filter/effect/parameter/value"))
    assert abs(val - 10 ** (6 / 20)) < 1e-3


def test_clip_audio_gain_zero_emits_no_filter():
    tracks = [
        {
            "name": "V1", "audio_muted": False, "audio_volume": 1.0,
            "clips": [
                {"video_id": 1, "timeline_start": 0.0, "source_in": 0.0, "source_out": 4.0,
                 "audio_gain_db": 0.0, "norm_gain_db": 0.0},
            ],
        }
    ]
    root = ET.fromstring(build_xmeml("t", VIDEOS, tracks, None, normalize_audio=True))
    clip = root.find("sequence/media/audio/track/clipitem")
    assert clip.find("filter") is None  # unity -> no Audio Levels filter
