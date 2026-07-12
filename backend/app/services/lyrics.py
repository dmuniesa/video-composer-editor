"""Lyrics + vocal analysis of the song with a local Whisper model
(faster-whisper): transcribes the sung lines with timestamps and derives
where the vocals are, so the UI and the AI composer can tell verses from
melody-only (instrumental) passages.

faster-whisper is an optional dependency (pip install faster-whisper) and its
import is deferred, mirroring how librosa is handled in audio_analysis."""
from __future__ import annotations

import logging
import os
import sys
from importlib import util as importlib_util
from pathlib import Path

log = logging.getLogger(__name__)


def _register_cuda_dll_dirs() -> None:
    """On Windows, ctranslate2 (faster-whisper's backend) loads CUDA/cuDNN
    with a raw LoadLibrary call that only honors the process PATH, not
    os.add_dll_directory. pip installs the nvidia-cublas-cu12 /
    nvidia-cudnn-cu12 wheels' DLLs under site-packages, which is never on
    PATH -- GPU transcription fails with "cublas64_12.dll is not found" even
    though the file is right there. Prepend those dirs to PATH."""
    if sys.platform != "win32":
        return
    dirs = []
    for pkg in ("nvidia.cublas.bin", "nvidia.cudnn.bin", "nvidia.cuda_nvrtc.bin"):
        spec = importlib_util.find_spec(pkg)
        if spec and spec.submodule_search_locations:
            dirs.extend(spec.submodule_search_locations)
    if dirs:
        os.environ["PATH"] = os.pathsep.join([*dirs, os.environ.get("PATH", "")])

# Whisper marks segments it suspects are not speech; above this we drop them.
MAX_NO_SPEECH_PROB = 0.6
# Vocal segments closer than this are merged into one vocal range (breaths,
# short pauses between lines).
JOIN_GAP_SECONDS = 2.0


def available() -> bool:
    return importlib_util.find_spec("faster_whisper") is not None


def unavailable_reason() -> str:
    return (
        "faster-whisper is not installed. Install it in the backend environment "
        "(pip install faster-whisper) to transcribe lyrics."
    )


def transcribe(path: Path, model_name: str = "small", language: str = "") -> dict:
    """Transcribe the song. Returns {"language": str, "segments": [...]}, where
    each segment is {"start", "end", "text"} for one sung line. The first call
    downloads the Whisper model, so it can take a while."""
    _register_cuda_dll_dirs()
    from faster_whisper import WhisperModel

    log.info("transcribing lyrics: model=%s language=%s file=%s", model_name, language or "auto", path)
    model = WhisperModel(model_name, device="auto", compute_type="auto")
    raw_segments, info = model.transcribe(
        str(path),
        language=language or None,
        # Skip the accompaniment-only stretches instead of hallucinating
        # lyrics over them; music between lines is exactly what we must keep
        # out of the transcript.
        vad_filter=True,
        condition_on_previous_text=False,
    )
    segments = []
    for seg in raw_segments:
        text = seg.text.strip()
        if not text or seg.no_speech_prob > MAX_NO_SPEECH_PROB:
            continue
        segments.append(
            {"start": round(float(seg.start), 2), "end": round(float(seg.end), 2), "text": text}
        )
    return {"language": info.language or "", "segments": segments}


def vocal_ranges(segments: list[dict], join_gap: float = JOIN_GAP_SECONDS) -> list[dict]:
    """Merge transcript segments into continuous vocal ranges."""
    ranges: list[dict] = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        start, end = float(seg["start"]), float(seg["end"])
        if end <= start:
            continue
        if ranges and start - ranges[-1]["end"] <= join_gap:
            ranges[-1]["end"] = max(ranges[-1]["end"], end)
        else:
            ranges.append({"start": start, "end": end})
    return ranges


def instrumental_ranges(vocals: list[dict], duration: float, min_gap: float) -> list[dict]:
    """Gaps between vocal ranges at least min_gap long: intros, solos,
    bridges, outros — the melody-only passages."""
    if duration <= 0:
        return []
    if not vocals:
        return [{"start": 0.0, "end": round(duration, 2)}]
    gaps: list[dict] = []
    cursor = 0.0
    for r in vocals:
        if r["start"] - cursor >= min_gap:
            gaps.append({"start": round(cursor, 2), "end": round(r["start"], 2)})
        cursor = max(cursor, r["end"])
    if duration - cursor >= min_gap:
        gaps.append({"start": round(cursor, 2), "end": round(duration, 2)})
    return gaps


def vocal_ratio(start: float, end: float, vocals: list[dict]) -> float:
    """Fraction (0-1) of [start, end) covered by vocal ranges."""
    span = end - start
    if span <= 0:
        return 0.0
    covered = sum(
        max(0.0, min(end, r["end"]) - max(start, r["start"])) for r in vocals
    )
    return round(min(1.0, covered / span), 3)


def lines_between(segments: list[dict], start: float, end: float) -> list[str]:
    """Transcript lines whose midpoint falls inside [start, end)."""
    return [
        s["text"]
        for s in segments
        if start <= (float(s["start"]) + float(s["end"])) / 2 < end
    ]


def attach_hints(sections: list[dict], segments: list[dict], snippet_chars: int = 120) -> list[dict]:
    """Annotate section dicts (start/end/...) with "vocal_ratio" and a short
    "lyrics" snippet, for the AI section-labeling prompt."""
    vocals = vocal_ranges(segments)
    for s in sections:
        s["vocal_ratio"] = vocal_ratio(s["start"], s["end"], vocals)
        snippet = " / ".join(lines_between(segments, s["start"], s["end"]))
        if len(snippet) > snippet_chars:
            snippet = snippet[: snippet_chars - 1] + "…"
        s["lyrics"] = snippet
    return sections
