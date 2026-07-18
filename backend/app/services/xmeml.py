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
    # pathname2url is platform-specific: on Windows a drive path yields
    # '///C:/...' (three slashes), on POSIX '/path/...'. Normalise to a single
    # leading slash so the URL is always file://localhost/<path> — otherwise the
    # extra slashes make Windows drive paths import as UNC (\\C:\...) and
    # Premiere shows the media as missing.
    url = urllib.request.pathname2url(str(Path(path).resolve()))
    return "file://localhost/" + url.lstrip("/")


def _el(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, tag)
    if text is not None:
        el.text = text
    return el


def _rate_el(parent: ET.Element, timebase: int, ntsc: str) -> None:
    rate = _el(parent, "rate")
    _el(rate, "timebase", str(timebase))
    _el(rate, "ntsc", ntsc)


def _link(
    item: ET.Element,
    ref: str,
    mediatype: str,
    trackindex: int,
    clipindex: int,
    groupindex: int | None = None,
) -> None:
    """A <link> ties clipitems that must move together (a clip's video and its
    two audio channels), so Premiere treats them as one linked A/V clip."""
    link = _el(item, "link")
    _el(link, "linkclipref", ref)
    _el(link, "mediatype", mediatype)
    _el(link, "trackindex", str(trackindex))
    _el(link, "clipindex", str(clipindex))
    if groupindex is not None:
        _el(link, "groupindex", str(groupindex))


def _speed_param(effect: ET.Element, pid: str, value: str, vmin: str | None = None, vmax: str | None = None) -> None:
    param = _el(effect, "parameter")
    _el(param, "parameterid", pid)
    _el(param, "name", pid)
    if vmin is not None:
        _el(param, "valuemin", vmin)
    if vmax is not None:
        _el(param, "valuemax", vmax)
    _el(param, "value", value)


def _speed_filter(item: ET.Element, speed: float) -> None:
    """Constant-speed Time Remap motion filter — the representation Premiere
    itself writes/reads for speed-changed clips in FCP7 XML."""
    filt = _el(item, "filter")
    effect = _el(filt, "effect")
    _el(effect, "name", "Time Remap")
    _el(effect, "effectid", "timeremap")
    _el(effect, "effectcategory", "motion")
    _el(effect, "effecttype", "motion")
    _el(effect, "mediatype", "video")
    _speed_param(effect, "variablespeed", "0", "0", "1")
    _speed_param(effect, "speed", str(round(speed * 100, 2)), "-100000", "100000")
    _speed_param(effect, "reverse", "FALSE")
    _speed_param(effect, "frameblending", "FALSE")


def _audio_level_filter(item: ET.Element, level: float) -> None:
    """Audio Levels filter setting a clip's gain — the FCP7 XML representation
    Premiere reads for a per-clip volume change (level is linear, 1.0 == 0 dB)."""
    filt = _el(item, "filter")
    effect = _el(filt, "effect")
    _el(effect, "name", "Audio Levels")
    _el(effect, "effectid", "audiolevels")
    _el(effect, "effectcategory", "audiolevels")
    _el(effect, "effecttype", "audiolevels")
    _el(effect, "mediatype", "audio")
    param = _el(effect, "parameter")
    _el(param, "parameterid", "level")
    _el(param, "name", "Level")
    _el(param, "valuemin", "0")
    _el(param, "valuemax", "3.98107")
    _el(param, "value", str(round(level, 4)))


# FCP7 Audio Levels filter caps at 3.98107 (~+12 dB); clamp the combined level so
# the emitted <value> stays in range.
_LEVEL_MAX = 3.98107


def _clip_linear_level(
    track_volume: float, audio_gain_db: float, norm_gain_db: float, normalize_audio: bool
) -> float:
    """Linear audio level for one clip = track volume × per-clip dB gain, clamped
    to the filter's max. The per-clip gain folds the stored normalisation gain
    (only when normalisation is on) and the user's manual dB offset."""
    final_db = (norm_gain_db if normalize_audio else 0.0) + audio_gain_db
    level = (track_volume or 1.0) * 10.0 ** (final_db / 20.0)
    return max(0.0, min(level, _LEVEL_MAX))


def build_xmeml(
    sequence_name: str,
    videos: dict[int, dict],
    tracks: list[dict],
    song: dict | None,
    sequence_fps: float = 0.0,
    sequence_width: int = 0,
    sequence_height: int = 0,
    normalize_audio: bool = False,
) -> str:
    """Build the project XML.

    videos: {video_id: {path, fps, width, height, duration}}
    tracks: [{name, clips: [{video_id, timeline_start, source_in, source_out, speed?}]}]
    song:   {path, duration} or None
    sequence_fps: composition frame rate; falls back to the dominant source fps
    sequence_width/height: composition frame size; falls back to the dominant source size
    """
    fps_values = [round(v["fps"], 3) for v in videos.values() if v.get("fps")]
    dominant_fps = Counter(fps_values).most_common(1)[0][0] if fps_values else 25.0
    timebase, ntsc = _rate_for(sequence_fps or dominant_fps)

    def frames(seconds: float) -> int:
        return int(round(seconds * timebase))

    def clip_len(c: dict) -> float:
        return (c["source_out"] - c["source_in"]) / (c.get("speed") or 1.0)

    used_clips = [c for t in tracks for c in t["clips"]]
    total_end = max(
        [frames(c["timeline_start"] + clip_len(c)) for c in used_clips]
        + ([frames(song["duration"])] if song else [0])
        + [0]
    )

    root = ET.Element("xmeml", version="5")
    seq = _el(root, "sequence")
    seq.set("id", "sequence-1")
    # Premiere writes stereo timeline tracks as two "exploded" mono tracks; this
    # flag tells it the audio tracks below are in that exploded form.
    seq.set("explodedTracks", "true")
    _el(seq, "name", sequence_name)
    _el(seq, "duration", str(total_end))
    _rate_el(seq, timebase, ntsc)

    media = _el(seq, "media")
    video_el = _el(media, "video")

    fmt = _el(video_el, "format")
    sc = _el(fmt, "samplecharacteristics")
    _rate_el(sc, timebase, ntsc)
    if sequence_width and sequence_height:
        width, height = sequence_width, sequence_height
    else:
        sizes = [(v["width"], v["height"]) for v in videos.values() if v.get("width")]
        width, height = (Counter(sizes).most_common(1)[0][0] if sizes else (1920, 1080))
    _el(sc, "width", str(width))
    _el(sc, "height", str(height))
    _el(sc, "anamorphic", "FALSE")
    _el(sc, "pixelaspectratio", "square")

    file_ids: dict[int, str] = {}
    clip_counter = 0
    # Audio track layout (top to bottom): the song on the first stereo track,
    # then one stereo track per video track carrying that track's clip audio.
    # Each stereo track is written as two "exploded" mono tracks (see below), so
    # the song takes exploded audio tracks 1 & 2 and video track i's audio takes
    # audio_base + 2i + 1/2.
    audio_base = 2 if song else 0
    clip_records: list[dict] = []

    for i, track in enumerate(tracks):
        track_el = _el(video_el, "track")
        for j, clip in enumerate(track["clips"]):
            clip_counter += 1
            v = videos[clip["video_id"]]
            v_timebase, v_ntsc = _rate_for(v.get("fps") or dominant_fps)
            speed = clip.get("speed") or 1.0
            start_f = frames(clip["timeline_start"])
            end_f = frames(clip["timeline_start"] + clip_len(clip))
            in_f = int(round(clip["source_in"] * v_timebase))
            if abs(speed - 1.0) < 1e-6:
                out_f = in_f + (end_f - start_f)
            else:
                out_f = int(round(clip["source_out"] * v_timebase))

            name = Path(v["path"]).name
            vid_id = f"clipitem-{clip_counter}"
            a_l, a_r = f"audioclip-{clip_counter}-1", f"audioclip-{clip_counter}-2"
            vt, vc = i + 1, j + 1  # this clip's video track / position (1-based)
            at1, at2 = audio_base + 2 * i + 1, audio_base + 2 * i + 2

            item = _el(track_el, "clipitem")
            item.set("id", vid_id)
            _el(item, "name", name)
            _el(item, "enabled", "TRUE")
            _el(item, "duration", str(int(math.ceil((v.get("duration") or 0) * v_timebase))))
            _rate_el(item, v_timebase, v_ntsc)
            _el(item, "start", str(start_f))
            _el(item, "end", str(end_f))
            _el(item, "in", str(in_f))
            _el(item, "out", str(out_f))

            file_el = _el(item, "file")
            vidkey = clip["video_id"]
            if vidkey not in file_ids:
                file_ids[vidkey] = f"file-{len(file_ids) + 1}"
                file_el.set("id", file_ids[vidkey])
                _el(file_el, "name", name)
                _el(file_el, "pathurl", _pathurl(v["path"]))
                _rate_el(file_el, v_timebase, v_ntsc)
                _el(file_el, "duration", str(int(math.ceil((v.get("duration") or 0) * v_timebase))))
                fmedia = _el(file_el, "media")
                fvideo = _el(fmedia, "video")
                fsc = _el(fvideo, "samplecharacteristics")
                _el(fsc, "width", str(v.get("width") or width))
                _el(fsc, "height", str(v.get("height") or height))
                # Declare the source's (assumed stereo) audio so its channels can
                # be laid on the timeline as a linked stereo clip further down.
                faudio = _el(fmedia, "audio")
                fasc = _el(faudio, "samplecharacteristics")
                _el(fasc, "depth", "16")
                _el(fasc, "samplerate", "48000")
                _el(faudio, "channelcount", "2")
            else:
                file_el.set("id", file_ids[vidkey])
            if abs(speed - 1.0) >= 1e-6:
                _speed_filter(item, speed)
            # Link the video clip down to its two audio channels so they stay
            # together as one A/V clip when edited in Premiere.
            _link(item, vid_id, "video", vt, vc)
            _link(item, a_l, "audio", at1, vc, 1)
            _link(item, a_r, "audio", at2, vc, 1)

            # Audio is placed entirely in sequence-rate space so each channel's
            # length matches the clip's timeline footprint (no per-clip retime on
            # audio — speed-changed clips keep sync in length, playing 1x).
            a_in = int(round(clip["source_in"] * timebase))
            clip_records.append(
                {
                    "i": i, "name": name, "file_id": file_ids[vidkey],
                    "start_f": start_f, "end_f": end_f,
                    "a_in": a_in, "a_out": a_in + (end_f - start_f),
                    "a_dur": int(math.ceil((v.get("duration") or 0) * timebase)),
                    "vid_id": vid_id, "a_l": a_l, "a_r": a_r,
                    "vt": vt, "vc": vc, "at1": at1, "at2": at2,
                    # Pre-combined linear level (track volume × per-clip gain).
                    "level": _clip_linear_level(
                        track.get("audio_volume", 1.0),
                        clip.get("audio_gain_db") or 0.0,
                        clip.get("norm_gain_db") or 0.0,
                        normalize_audio,
                    ),
                }
            )

    audio_el = _el(media, "audio")

    def stereo_track_pair(specs: list[dict], muted: bool = False, volume: float = 1.0) -> None:
        """Emit one stereo timeline track as two "exploded" mono <track>s.

        Premiere models a stereo timeline track as two mono tracks (one per
        channel) tied together by premiereTrackType="Stereo" and a shared
        currentExplodedTrackIndex/totalExplodedTrackCount, with each clip split
        into two channel clipitems (sourcetrack index 1 and 2) marked
        premiereChannelType="stereo" and linked. Without these markers Premiere
        imports the channels as two separate mono L/R tracks.

        A muted lane is written with the track disabled (<enabled>FALSE</enabled>);
        a volume below 1.0 adds an Audio Levels filter to each clip.
        """
        for channel in (1, 2):
            track_el = _el(audio_el, "track")
            track_el.set("premiereTrackType", "Stereo")
            track_el.set("currentExplodedTrackIndex", str(channel - 1))
            track_el.set("totalExplodedTrackCount", "2")
            for spec in specs:
                item = _el(track_el, "clipitem")
                item.set("id", spec["a_l"] if channel == 1 else spec["a_r"])
                item.set("premiereChannelType", "stereo")
                _el(item, "name", spec["name"])
                _el(item, "enabled", "TRUE")
                _el(item, "duration", str(spec["a_dur"]))
                _rate_el(item, timebase, ntsc)
                _el(item, "start", str(spec["start_f"]))
                _el(item, "end", str(spec["end_f"]))
                _el(item, "in", str(spec["a_in"]))
                _el(item, "out", str(spec["a_out"]))
                file_el = _el(item, "file")
                # The song defines its own <file> here (channel 1); clip audio
                # reuses the <file> already defined on its video clipitem.
                if spec.get("define_file") and channel == 1:
                    file_el.set("id", spec["file_id"])
                    _el(file_el, "name", spec["name"])
                    _el(file_el, "pathurl", spec["pathurl"])
                    _rate_el(file_el, timebase, ntsc)
                    _el(file_el, "duration", str(spec["a_dur"]))
                    fmedia = _el(file_el, "media")
                    faudio = _el(fmedia, "audio")
                    fasc = _el(faudio, "samplecharacteristics")
                    _el(fasc, "depth", "16")
                    _el(fasc, "samplerate", "48000")
                    _el(faudio, "channelcount", "2")
                else:
                    file_el.set("id", spec["file_id"])
                # Per-clip level when the spec carries one (clip audio), else the
                # track/song volume passed in (song has no per-clip gain).
                level = spec.get("level", volume)
                if abs(level - 1.0) > 1e-3:
                    _audio_level_filter(item, level)
                source_track = _el(item, "sourcetrack")
                _el(source_track, "mediatype", "audio")
                _el(source_track, "trackindex", str(channel))
                if spec.get("vid_id"):  # clip audio links back up to its video
                    _link(item, spec["vid_id"], "video", spec["vt"], spec["vc"])
                _link(item, spec["a_l"], "audio", spec["at1"], spec["ac"], 1)
                _link(item, spec["a_r"], "audio", spec["at2"], spec["ac"], 1)
            _el(track_el, "enabled", "FALSE" if muted else "TRUE")
            _el(track_el, "locked", "FALSE")
            _el(track_el, "outputchannelindex", str(channel))

    if song or clip_records:
        # Stereo master: two output channels, each its own mono output group.
        _el(audio_el, "numOutputChannels", "2")
        fmt = _el(audio_el, "format")
        asc = _el(fmt, "samplecharacteristics")
        _el(asc, "depth", "16")
        _el(asc, "samplerate", "48000")
        outputs = _el(audio_el, "outputs")
        for ch in (1, 2):
            group = _el(outputs, "group")
            _el(group, "index", str(ch))
            _el(group, "numchannels", "1")
            _el(group, "downmix", "0")
            channel_el = _el(group, "channel")
            _el(channel_el, "index", str(ch))

        if song:
            song_frames = frames(song["duration"])
            stereo_track_pair(
                [
                    {
                        "name": Path(song["path"]).name,
                        "a_dur": song_frames, "start_f": 0, "end_f": song_frames,
                        "a_in": 0, "a_out": song_frames,
                        "file_id": "file-song", "define_file": True,
                        "pathurl": _pathurl(song["path"]),
                        "a_l": "audioclip-song-1", "a_r": "audioclip-song-2",
                        "at1": 1, "at2": 2, "ac": 1,
                    }
                ],
                muted=bool(song.get("muted")),
                volume=float(song.get("volume", 1.0) or 1.0),
            )

        # One stereo audio track per video track, below the song.
        for i, track in enumerate(tracks):
            stereo_track_pair(
                [{**r, "ac": r["vc"]} for r in clip_records if r["i"] == i],
                muted=bool(track.get("audio_muted")),
                volume=float(track.get("audio_volume", 1.0) or 1.0),
            )

    xml_bytes = ET.tostring(root, encoding="unicode")
    pretty = minidom.parseString(xml_bytes).toprettyxml(indent="  ")
    # minidom puts an <?xml?> header without DOCTYPE; add the xmeml doctype.
    body = pretty.split("\n", 1)[1]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body
