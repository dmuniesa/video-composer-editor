"""FCP7 XML (xmeml v5) generator — the interchange format Adobe Premiere Pro
imports directly as a sequence (File > Import), referencing the original
media files on disk.

Times are stored in seconds and converted to integer frames at the sequence
rate; per-file rates use each source's own fps and rely on Premiere's
conform-on-import for mixed-fps material."""
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


def _rate_for(fps: float) -> tuple[int, str]:
    """Map a real fps to (timebase, ntsc flag) the xmeml way."""
    if fps <= 0:
        return 25, "FALSE"
    timebase = int(round(fps))
    for tb, real in NTSC_TIMEBASES.items():
        if abs(fps - real) < 0.01:
            return tb, "TRUE"
    return timebase, "FALSE"


def _pathurl(path: str) -> str:
    return "file://localhost" + urllib.request.pathname2url(str(Path(path).resolve()))


def _el(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _rate_el(parent: ET.Element, timebase: int, ntsc: str) -> None:
    rate = _el(parent, "rate")
    _el(rate, "timebase", str(timebase))
    _el(rate, "ntsc", ntsc)


def build_xmeml(
    sequence_name: str,
    videos: dict[int, dict],
    tracks: list[dict],
    song: dict | None,
) -> str:
    """Build the project XML.

    videos: {video_id: {path, fps, width, height, duration}}
    tracks: [{name, clips: [{video_id, timeline_start, source_in, source_out}]}]
    song:   {path, duration} or None
    """
    fps_values = [round(v["fps"], 3) for v in videos.values() if v.get("fps")]
    dominant_fps = Counter(fps_values).most_common(1)[0][0] if fps_values else 25.0
    timebase, ntsc = _rate_for(dominant_fps)

    def frames(seconds: float) -> int:
        return int(round(seconds * timebase))

    used_clips = [c for t in tracks for c in t["clips"]]
    total_end = max(
        [frames(c["timeline_start"] + (c["source_out"] - c["source_in"])) for c in used_clips]
        + ([frames(song["duration"])] if song else [0])
        + [0]
    )

    root = ET.Element("xmeml", version="5")
    seq = _el(root, "sequence")
    seq.set("id", "sequence-1")
    _el(seq, "name", sequence_name)
    _el(seq, "duration", str(total_end))
    _rate_el(seq, timebase, ntsc)

    media = _el(seq, "media")
    video_el = _el(media, "video")

    fmt = _el(video_el, "format")
    sc = _el(fmt, "samplecharacteristics")
    _rate_el(sc, timebase, ntsc)
    sizes = [(v["width"], v["height"]) for v in videos.values() if v.get("width")]
    width, height = (Counter(sizes).most_common(1)[0][0] if sizes else (1920, 1080))
    _el(sc, "width", str(width))
    _el(sc, "height", str(height))
    _el(sc, "anamorphic", "FALSE")
    _el(sc, "pixelaspectratio", "square")

    file_ids: dict[int, str] = {}
    clip_counter = 0

    for track in tracks:
        track_el = _el(video_el, "track")
        for clip in track["clips"]:
            clip_counter += 1
            v = videos[clip["video_id"]]
            v_timebase, v_ntsc = _rate_for(v.get("fps") or dominant_fps)
            start_f = frames(clip["timeline_start"])
            end_f = frames(clip["timeline_start"] + (clip["source_out"] - clip["source_in"]))
            in_f = int(round(clip["source_in"] * v_timebase))
            out_f = in_f + (end_f - start_f)

            item = _el(track_el, "clipitem")
            item.set("id", f"clipitem-{clip_counter}")
            _el(item, "name", Path(v["path"]).name)
            _el(item, "enabled", "TRUE")
            _el(item, "duration", str(int(math.ceil((v.get("duration") or 0) * v_timebase))))
            _rate_el(item, v_timebase, v_ntsc)
            _el(item, "start", str(start_f))
            _el(item, "end", str(end_f))
            _el(item, "in", str(in_f))
            _el(item, "out", str(out_f))

            file_el = _el(item, "file")
            vid = clip["video_id"]
            if vid not in file_ids:
                file_ids[vid] = f"file-{len(file_ids) + 1}"
                file_el.set("id", file_ids[vid])
                _el(file_el, "name", Path(v["path"]).name)
                _el(file_el, "pathurl", _pathurl(v["path"]))
                _rate_el(file_el, v_timebase, v_ntsc)
                _el(file_el, "duration", str(int(math.ceil((v.get("duration") or 0) * v_timebase))))
                fmedia = _el(file_el, "media")
                fvideo = _el(fmedia, "video")
                fsc = _el(fvideo, "samplecharacteristics")
                _el(fsc, "width", str(v.get("width") or width))
                _el(fsc, "height", str(v.get("height") or height))
                _el(fmedia, "audio")
            else:
                file_el.set("id", file_ids[vid])

    audio_el = _el(media, "audio")
    if song:
        song_frames = frames(song["duration"])
        for channel in (1, 2):
            track_el = _el(audio_el, "track")
            item = _el(track_el, "clipitem")
            item.set("id", f"audioclip-{channel}")
            _el(item, "name", Path(song["path"]).name)
            _el(item, "enabled", "TRUE")
            _el(item, "duration", str(song_frames))
            _rate_el(item, timebase, ntsc)
            _el(item, "start", "0")
            _el(item, "end", str(song_frames))
            _el(item, "in", "0")
            _el(item, "out", str(song_frames))
            file_el = _el(item, "file")
            if channel == 1:
                file_el.set("id", "file-song")
                _el(file_el, "name", Path(song["path"]).name)
                _el(file_el, "pathurl", _pathurl(song["path"]))
                _rate_el(file_el, timebase, ntsc)
                _el(file_el, "duration", str(song_frames))
                fmedia = _el(file_el, "media")
                faudio = _el(fmedia, "audio")
                fsc = _el(faudio, "samplecharacteristics")
                _el(fsc, "samplerate", "48000")
                _el(fsc, "depth", "16")
                _el(faudio, "channelcount", "2")
            else:
                file_el.set("id", "file-song")
            source_track = _el(item, "sourcetrack")
            _el(source_track, "mediatype", "audio")
            _el(source_track, "trackindex", str(channel))

    xml_bytes = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
    # minidom puts an <?xml?> header without DOCTYPE; add the xmeml doctype.
    body = pretty.split("\n", 1)[1]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body
