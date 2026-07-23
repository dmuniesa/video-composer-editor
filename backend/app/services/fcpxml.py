"""FCPXML 1.9 generator — the interchange format Final Cut Pro X imports
directly (File > Import > XML), referencing the original media files on disk.

FCPX has a magnetic primary storyline rather than free tracks, so the montage
is exported as one gap element spanning the whole song with every clip
connected to it: video track N becomes lane N+1 (higher lanes sit on top) and
the song sits on lane -1, keeping the exact timeline positions.

All times are expressed as rational seconds on the sequence's frame duration
(the FCPXML convention), snapping each edit to the sequence rate the same way
the xmeml exporter does."""
from __future__ import annotations

import math
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from xml.dom import minidom
from xml.etree import ElementTree as ET

# fps values that are NTSC-style fractional rates (timebase/1.001)
NTSC_TIMEBASES = {24: 23.976, 30: 29.97, 60: 59.94}


def _frame_duration(fps: float) -> tuple[int, int]:
    """Map a real fps to a (numerator, denominator) frame duration in seconds."""
    if fps <= 0:
        return 1, 25
    for tb, real in NTSC_TIMEBASES.items():
        if abs(fps - real) < 0.01:
            return 1001, tb * 1000
    return 1, int(round(fps))


def _src_url(path: str) -> str:
    # Local drive paths -> the canonical file:///<drive>/... form (pathname2url
    # plus a single leading slash on Windows). UNC network paths
    # (\\host\share\...) need the RFC 8089 file://<host>/<share>/... authority
    # form instead — 'file:///<host>' would make the host a path segment and the
    # media can't be relinked.
    s = str(Path(path).resolve())
    if s.startswith("\\\\"):  # UNC: \\host\share\...
        host, rest = s.lstrip("\\").split("\\", 1)
        return "file://" + host + "/" + urllib.parse.quote(rest.replace("\\", "/"))
    url = urllib.request.pathname2url(s)
    return "file:///" + url.lstrip("/")


def _db_str(db: float) -> str:
    """Format a dB value for a FCPXML ``amount`` attribute: -3 -> '-3dB',
    0 -> '0dB', 2.5 -> '+2.5dB'."""
    if abs(db) < 1e-3:
        return "0dB"
    return f"{round(db, 2):+g}dB"


def _clip_gain_db(audio_gain_db: float, norm_gain_db: float, normalize_audio: bool) -> float:
    """Per-clip audio gain in dB = normalisation gain (when on) + user offset."""
    return (norm_gain_db if normalize_audio else 0.0) + audio_gain_db


def build_fcpxml(
    sequence_name: str,
    videos: dict[int, dict],
    tracks: list[dict],
    song: dict | None,
    sequence_fps: float = 0.0,
    sequence_width: int = 0,
    sequence_height: int = 0,
    normalize_audio: bool = False,
) -> str:
    """Build the project XML. Takes the same inputs as xmeml.build_xmeml:

    videos: {video_id: {path, fps, width, height, duration}}
    tracks: [{name, clips: [{video_id, timeline_start, source_in, source_out, speed?}]}]
    song:   {path, duration} or None
    sequence_fps: composition frame rate; falls back to the dominant source fps

    Clip speed only affects each clip's timeline footprint here; the FCPX
    retime effect (<timeMap>) is not emitted, so retimed clips import at the
    right length but play 1x — use the xmeml export for real speed changes.
    """
    fps_values = [round(v["fps"], 3) for v in videos.values() if v.get("fps")]
    dominant_fps = Counter(fps_values).most_common(1)[0][0] if fps_values else 25.0
    num, den = _frame_duration(sequence_fps or dominant_fps)
    fps = den / num

    def frames(seconds: float) -> int:
        return int(round(seconds * fps))

    def t(frame_count: int) -> str:
        return f"{frame_count * num}/{den}s"

    def clip_len(c: dict) -> float:
        return (c["source_out"] - c["source_in"]) / (c.get("speed") or 1.0)

    used_clips = [c for tr in tracks for c in tr["clips"]]
    total_end = max(
        [frames(c["timeline_start"] + clip_len(c)) for c in used_clips]
        + ([frames(song["duration"])] if song else [0])
        + [1]
    )

    if sequence_width and sequence_height:
        width, height = sequence_width, sequence_height
    else:
        sizes = [(v["width"], v["height"]) for v in videos.values() if v.get("width")]
        width, height = (Counter(sizes).most_common(1)[0][0] if sizes else (1920, 1080))

    root = ET.Element("fcpxml", version="1.9")
    resources = ET.SubElement(root, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        frameDuration=f"{num}/{den}s",
        width=str(width),
        height=str(height),
    )

    asset_ids: dict[int, str] = {}
    for vid, v in sorted(videos.items()):
        asset_ids[vid] = f"r{len(asset_ids) + 2}"
        asset = ET.SubElement(
            resources,
            "asset",
            id=asset_ids[vid],
            name=Path(v["path"]).name,
            start="0s",
            duration=t(int(math.ceil((v.get("duration") or 0) * fps))),
            hasVideo="1",
            hasAudio="1",
        )
        ET.SubElement(asset, "media-rep", kind="original-media", src=_src_url(v["path"]))
    if song:
        song_asset = ET.SubElement(
            resources,
            "asset",
            id="r-song",
            name=Path(song["path"]).name,
            start="0s",
            duration=t(frames(song["duration"])),
            hasAudio="1",
            audioSources="1",
            audioChannels="2",
        )
        ET.SubElement(song_asset, "media-rep", kind="original-media", src=_src_url(song["path"]))

    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name=sequence_name)
    project = ET.SubElement(event, "project", name=sequence_name)
    sequence = ET.SubElement(
        project, "sequence", format="r1", duration=t(total_end), tcStart="0s", tcFormat="NDF"
    )
    spine = ET.SubElement(sequence, "spine")

    gap = ET.SubElement(spine, "gap", name="Montage", offset="0s", start="0s", duration=t(total_end))

    if song:
        ET.SubElement(
            gap,
            "asset-clip",
            ref="r-song",
            lane="-1",
            offset="0s",
            start="0s",
            duration=t(frames(song["duration"])),
            name=Path(song["path"]).name,
        )

    for track_index, track in enumerate(tracks):
        for clip in track["clips"]:
            v = videos[clip["video_id"]]
            start_f = frames(clip["timeline_start"])
            dur_f = frames(clip["timeline_start"] + clip_len(clip)) - start_f
            if dur_f <= 0:
                continue
            clip_el = ET.SubElement(
                gap,
                "asset-clip",
                ref=asset_ids[clip["video_id"]],
                lane=str(track_index + 1),
                offset=t(start_f),
                start=t(frames(clip["source_in"])),
                duration=t(dur_f),
                name=Path(v["path"]).name,
            )
            # Per-clip audio gain (normalisation gain when enabled + user offset)
            # as a FCPXML <adjust-volume> effect, the representation Final Cut
            # reads for a clip volume change.
            gain_db = _clip_gain_db(
                clip.get("audio_gain_db") or 0.0,
                clip.get("norm_gain_db") or 0.0,
                normalize_audio,
            )
            if abs(gain_db) > 1e-3:
                ET.SubElement(clip_el, "adjust-volume", amount=_db_str(gain_db))

    xml_bytes = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
    body = pretty.split("\n", 1)[1]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + body
