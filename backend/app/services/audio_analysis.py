"""Local music analysis with librosa: tempo, beats, downbeats, structural
sections, and waveform peaks for the timeline UI.

librosa import is deferred: it drags in numba and takes seconds, so only the
song-analysis job pays that cost."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PEAK_BUCKETS = 2000
MIN_SECTION_SECONDS = 8.0


@dataclass
class AudioAnalysis:
    duration: float
    bpm: float
    beats: list[float]
    downbeats: list[float]
    # sections: {start, end, energy, cluster}
    sections: list[dict] = field(default_factory=list)


def compute_peaks(path: Path, dest: Path, buckets: int = PEAK_BUCKETS) -> None:
    """Write min/max amplitude pairs per bucket as JSON for canvas drawing."""
    import librosa

    y, _sr = librosa.load(str(path), sr=8000, mono=True)
    if len(y) == 0:
        dest.write_text(json.dumps({"peaks": []}))
        return
    n = min(buckets, len(y))
    chunks = np.array_split(y, n)
    peaks = [[round(float(c.min()), 4), round(float(c.max()), 4)] for c in chunks]
    dest.write_text(json.dumps({"peaks": peaks}))


def analyze(path: Path) -> AudioAnalysis:
    import librosa

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    duration = float(len(y) / sr)

    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)
    bpm = float(np.atleast_1d(tempo)[0])
    beats = [float(t) for t in librosa.frames_to_time(beat_frames, sr=sr)]
    # Downbeat estimation: pick the beat phase (0..3) with the most onset energy.
    downbeats = _estimate_downbeats(y, sr, beat_frames)

    sections = _segment(y, sr, duration)

    return AudioAnalysis(
        duration=duration, bpm=bpm, beats=beats, downbeats=downbeats, sections=sections
    )


def _estimate_downbeats(y: np.ndarray, sr: int, beat_frames: np.ndarray) -> list[float]:
    import librosa

    if len(beat_frames) < 8:
        return []
    onset = librosa.onset.onset_strength(y=y, sr=sr)
    strengths = onset[np.clip(beat_frames, 0, len(onset) - 1)]
    best_phase = max(range(4), key=lambda p: float(strengths[p::4].sum()))
    times = librosa.frames_to_time(beat_frames[best_phase::4], sr=sr)
    return [float(t) for t in times]


def _segment(y: np.ndarray, sr: int, duration: float) -> list[dict]:
    """Structural segmentation: agglomerative clustering over stacked
    chroma+MFCC features, then k-means over segment means to find which
    sections sound alike (verse vs chorus groups)."""
    import librosa

    if duration < MIN_SECTION_SECONDS * 2:
        return [{"start": 0.0, "end": duration, "energy": 1.0, "cluster": 0}]

    hop = 512
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr, hop_length=hop)
    mfcc = librosa.feature.mfcc(y=y, sr=sr, hop_length=hop, n_mfcc=13)
    feats = np.vstack([librosa.util.normalize(chroma, axis=0), librosa.util.normalize(mfcc, axis=0)])

    target = max(2, min(12, int(duration // 25)))
    bounds = librosa.segment.agglomerative(feats, target + 1)
    times = librosa.frames_to_time(bounds, sr=sr, hop_length=hop)
    edges = _clean_edges([0.0, *[float(t) for t in times], duration], duration)

    rms = librosa.feature.rms(y=y, hop_length=hop)[0]
    rms_times = librosa.times_like(rms, sr=sr, hop_length=hop)
    frame_times = librosa.times_like(feats[0], sr=sr, hop_length=hop)

    sections = []
    seg_means = []
    for start, end in zip(edges[:-1], edges[1:]):
        mask = (rms_times >= start) & (rms_times < end)
        energy = float(rms[mask].mean()) if mask.any() else 0.0
        fmask = (frame_times >= start) & (frame_times < end)
        seg_means.append(
            feats[:, fmask].mean(axis=1) if fmask.any() else np.zeros(feats.shape[0])
        )
        sections.append({"start": round(start, 2), "end": round(end, 2), "energy": energy})

    peak = max((s["energy"] for s in sections), default=1.0) or 1.0
    for s in sections:
        s["energy"] = round(s["energy"] / peak, 3)

    for i, cluster in enumerate(_cluster_segments(np.array(seg_means))):
        sections[i]["cluster"] = int(cluster)
    return sections


def _clean_edges(edges: list[float], duration: float) -> list[float]:
    """Sort, dedupe, and merge sections shorter than MIN_SECTION_SECONDS."""
    edges = sorted(set(round(e, 2) for e in edges if 0.0 <= e <= duration))
    if not edges or edges[0] != 0.0:
        edges.insert(0, 0.0)
    if edges[-1] != duration:
        edges.append(duration)
    cleaned = [edges[0]]
    for e in edges[1:-1]:
        if e - cleaned[-1] >= MIN_SECTION_SECONDS and duration - e >= MIN_SECTION_SECONDS:
            cleaned.append(e)
    cleaned.append(edges[-1])
    return cleaned


def _cluster_segments(means: np.ndarray, k: int | None = None) -> list[int]:
    """Tiny k-means (no sklearn dependency) grouping similar-sounding sections."""
    n = len(means)
    if n <= 2:
        return list(range(n))
    k = k or max(2, min(4, n // 2))
    rng = np.random.default_rng(0)
    centers = means[rng.choice(n, size=k, replace=False)]
    labels = np.zeros(n, dtype=int)
    for _ in range(25):
        dists = np.linalg.norm(means[:, None, :] - centers[None, :, :], axis=2)
        new_labels = dists.argmin(axis=1)
        if (new_labels == labels).all():
            break
        labels = new_labels
        for j in range(k):
            member = means[labels == j]
            if len(member):
                centers[j] = member.mean(axis=0)
    return [int(l) for l in labels]
