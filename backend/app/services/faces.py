"""People detection: face detection + identity embeddings with InsightFace
(SCRFD detector + ArcFace, ONNX on CPU), greedy clustering of unassigned faces
into Person rows, and cross-video matching against named persons' centroids.

The insightface/cv2 dependency is optional (pip install with the [faces]
extra): nothing here is imported at app startup, and available() gates every
entry point so the rest of the app works without it.

Sampled frames and face crops live under the video's cache dir:
<cache>/faces/src_NNN.jpg (detection input) and <cache>/faces/crop_<id>.jpg
(aligned crop served by /media/{pid}/face/{id})."""
from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import settings
from ..models import Face, Person, Video

log = logging.getLogger(__name__)

# ArcFace cosine similarity: same person is typically 0.5-0.75, different
# people < 0.3. Assignment to an existing person is a bit laxer than starting
# clusters so named persons keep accumulating their harder shots.
SIM_ASSIGN = 0.45  # auto-assign a new face to an existing person
SIM_CLUSTER = 0.50  # greedy clustering threshold for unassigned faces
DET_SCORE_MIN = 0.55  # drop weak detections
MIN_FACE_PX = 36  # min bbox side in pixels (at the sampled frame size)
FRAME_WIDTH = 960  # sampled frame width (analysis frames are too small)
CROP_SIZE = 192  # saved face-crop size (square-ish, padded bbox)

_import_error: str | None = None
_checked = False
_model = None
_model_pack = ""
_model_lock = threading.Lock()


def available() -> bool:
    """True when insightface + cv2 import cleanly (cached)."""
    global _checked, _import_error
    if not _checked:
        try:
            import cv2  # noqa: F401
            import insightface  # noqa: F401
        except Exception as exc:  # noqa: BLE001 - report any import failure
            _import_error = str(exc)
        _checked = True
    return _import_error is None


def unavailable_reason() -> str:
    if available():
        return ""
    return (
        "People detection needs the optional face libraries. Install them in "
        "the backend environment: pip install insightface onnxruntime "
        "opencv-python-headless "
        f"(import error: {_import_error})"
    )


def _get_model():
    """Singleton FaceAnalysis model; (re)loaded when the settings pack changes.
    First use downloads the pack (~30-280 MB) to ~/.insightface/models/."""
    global _model, _model_pack
    pack = settings.get().faces.model_pack
    with _model_lock:
        if _model is None or _model_pack != pack:
            from insightface.app import FaceAnalysis

            log.info("loading face model pack %s", pack)
            model = FaceAnalysis(
                name=pack,
                allowed_modules=["detection", "recognition"],
                providers=["CPUExecutionProvider"],
            )
            model.prepare(ctx_id=-1, det_size=(640, 640))
            _model = model
            _model_pack = pack
        return _model


# --- embedding helpers -------------------------------------------------------

def normalize(vec: np.ndarray) -> np.ndarray:
    vec = np.asarray(vec, dtype=np.float32).ravel()
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm > 0 else vec


def emb_to_blob(vec: np.ndarray) -> bytes:
    return normalize(vec).tobytes()


def blob_to_emb(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    # Embeddings are stored L2-normalized, so cosine == dot.
    return float(np.dot(a, b))


def recompute_centroid(db: Session, person: Person) -> None:
    """Centroid = normalized mean of member embeddings; None when empty."""
    members = [f for f in person.faces if not f.ignored]
    if not members:
        person.centroid = None
        return
    stack = np.stack([blob_to_emb(f.embedding) for f in members])
    person.centroid = emb_to_blob(stack.mean(axis=0))


# --- frame sampling ----------------------------------------------------------

def faces_dir(cache: Path) -> Path:
    return cache / "faces"


def crop_path(cache: Path, face_id: int) -> Path:
    return faces_dir(cache) / f"crop_{face_id}.jpg"


def extract_face_frames(video: Path, duration: float, cache: Path) -> list[tuple[int, float]]:
    """Sample frames for face detection into <cache>/faces/src_NNN.jpg in one
    ffmpeg pass. Returns [(frame_index, timestamp_seconds), ...]. Denser and
    larger than the AI analysis frames: faces need pixels."""
    conf = settings.get().faces
    dest = faces_dir(cache)
    if dest.is_dir():
        shutil.rmtree(dest)  # stale crops/frames from a previous run
    dest.mkdir(parents=True, exist_ok=True)
    interval = max(conf.frame_interval_s, duration / conf.max_frames if duration > 0 else 0)
    out = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video),
            "-vf", f"fps=1/{interval:.4f},scale={FRAME_WIDTH}:-2",
            "-q:v", "4",
            str(dest / "src_%03d.jpg"),
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {out.stderr.strip()[:400]}")
    frames = sorted(dest.glob("src_*.jpg"))
    # ffmpeg's fps filter emits the first frame at t~0, then one per interval;
    # src_%03d numbering starts at 1.
    return [
        (i, min((i - 1) * interval, max(duration, 0.0)))
        for i in range(1, len(frames) + 1)
    ]


def _src_frame(cache: Path, index: int) -> Path:
    return faces_dir(cache) / f"src_{index:03d}.jpg"


def save_crop(cache: Path, face: Face) -> None:
    """Cut a padded bbox crop from the source frame so the media endpoint can
    serve a plain file (no cv2 in the request path)."""
    import cv2

    img = cv2.imread(str(_src_frame(cache, face.frame_index)))
    if img is None:
        return
    ih, iw = img.shape[:2]
    x, y = face.x * iw, face.y * ih
    w, h = face.w * iw, face.h * ih
    pad = 0.35
    x0 = int(max(0, x - w * pad))
    y0 = int(max(0, y - h * pad))
    x1 = int(min(iw, x + w * (1 + pad)))
    y1 = int(min(ih, y + h * (1 + pad)))
    crop = img[y0:y1, x0:x1]
    if crop.size == 0:
        return
    scale = CROP_SIZE / max(crop.shape[:2])
    if scale < 1:
        crop = cv2.resize(crop, (round(crop.shape[1] * scale), round(crop.shape[0] * scale)))
    cv2.imwrite(str(crop_path(cache, face.id)), crop, [cv2.IMWRITE_JPEG_QUALITY, 88])


# --- detection ---------------------------------------------------------------

def detect_video(db: Session, video: Video, cache: Path, progress=None) -> int:
    """Sample frames, detect + embed faces, insert Face rows, auto-assign to
    existing persons. Returns the number of faces kept. `progress(pct, msg)`
    is optional. Existing Face rows of the video are replaced."""
    import cv2

    model = _get_model()

    for old in list(video.faces):
        db.delete(old)
    db.flush()

    video_path = None
    if video.source:
        video_path = Path(video.source.path) / video.rel_path
    if video_path is None or not video_path.is_file():
        raise RuntimeError("video file not found (source offline?)")

    if progress:
        progress(0.2, "sampling frames")
    frame_list = extract_face_frames(video_path, video.duration, cache)

    kept: list[Face] = []
    for n, (index, t) in enumerate(frame_list):
        if progress:
            progress(0.2 + 0.6 * (n / max(len(frame_list), 1)), f"detecting faces {n + 1}/{len(frame_list)}")
        img = cv2.imread(str(_src_frame(cache, index)))
        if img is None:
            continue
        ih, iw = img.shape[:2]
        for det in model.get(img):
            score = float(det.det_score)
            x0, y0, x1, y1 = [float(v) for v in det.bbox]
            if score < DET_SCORE_MIN or min(x1 - x0, y1 - y0) < MIN_FACE_PX:
                continue
            if det.normed_embedding is None:
                continue
            face = Face(
                video_id=video.id,
                frame_index=index,
                t=t,
                x=max(0.0, x0 / iw),
                y=max(0.0, y0 / ih),
                w=(x1 - x0) / iw,
                h=(y1 - y0) / ih,
                det_score=score,
                embedding=emb_to_blob(det.normed_embedding),
            )
            db.add(face)
            kept.append(face)
    db.flush()  # assign ids before cropping/matching

    if progress:
        progress(0.85, "saving crops")
    for face in kept:
        save_crop(cache, face)

    assign_to_persons(db, kept)
    return len(kept)


# --- matching & clustering ---------------------------------------------------

def _person_matchers(db: Session) -> list[tuple[Person, np.ndarray]]:
    """One embedding matrix per person: every member face plus the centroid.
    Matching against all members (nearest neighbor), not just the centroid,
    means a person "learns" — each confirmed face covers another pose/light,
    so the more faces a person has, the easier new ones match."""
    out: list[tuple[Person, np.ndarray]] = []
    for p in db.scalars(select(Person)):
        rows = [blob_to_emb(f.embedding) for f in p.faces if not f.ignored]
        if p.centroid is not None:
            rows.append(blob_to_emb(p.centroid))
        if rows:
            out.append((p, np.stack(rows)))
    return out


def assign_to_persons(db: Session, faces: list[Face]) -> int:
    """Attach each unassigned face to its best-matching existing person when
    the similarity clears SIM_ASSIGN. Returns how many got assigned."""
    candidates = _person_matchers(db)
    if not candidates:
        return 0
    assigned = 0
    touched: set[int] = set()
    for face in faces:
        if face.person_id is not None or face.ignored:
            continue
        emb = blob_to_emb(face.embedding)
        best, best_sim = None, SIM_ASSIGN
        for person, matrix in candidates:
            sim = float(np.max(matrix @ emb))
            if sim >= best_sim:
                best, best_sim = person, sim
        if best is not None:
            face.person_id = best.id
            face.similarity = best_sim
            touched.add(best.id)
            assigned += 1
    for pid in touched:
        person = db.get(Person, pid)
        if person is not None:
            recompute_centroid(db, person)
    return assigned


def cluster_unassigned(db: Session) -> int:
    """Greedy leader clustering of all unassigned faces into new unnamed
    Person rows (singletons included — someone may appear once). Named persons
    and already-assigned faces are never touched. Returns clusters created."""
    faces = [
        f
        for f in db.scalars(select(Face).where(Face.person_id.is_(None), Face.ignored.is_(False)))
    ]
    if not faces:
        return 0
    faces.sort(key=lambda f: f.det_score, reverse=True)

    clusters: list[tuple[list[Face], np.ndarray]] = []  # (members, running mean)
    for face in faces:
        emb = blob_to_emb(face.embedding)
        best_i, best_sim = -1, SIM_CLUSTER
        for i, (_, centroid) in enumerate(clusters):
            sim = cosine(emb, normalize(centroid))
            if sim >= best_sim:
                best_i, best_sim = i, sim
        if best_i >= 0:
            members, centroid = clusters[best_i]
            members.append(face)
            clusters[best_i] = (members, centroid + emb)
        else:
            clusters.append(([face], emb.copy()))

    for members, _ in clusters:
        person = Person(name="")
        db.add(person)
        db.flush()
        for f in members:
            f.person_id = person.id
            f.similarity = None
        person.cover_face_id = members[0].id  # highest det_score member
        recompute_centroid(db, person)
    return len(clusters)


def dissolve_unnamed(db: Session) -> int:
    """Delete unnamed persons and free their faces (used by re-cluster)."""
    count = 0
    for person in list(db.scalars(select(Person).where(Person.name == ""))):
        for f in list(person.faces):
            f.person_id = None
            f.similarity = None
        db.delete(person)
        count += 1
    return count


def recluster(db: Session) -> dict:
    """Re-cluster on demand: dissolve unnamed clusters, retry assignment of
    every free face against the named persons, then cluster the rest."""
    dissolved = dissolve_unnamed(db)
    db.flush()
    free = list(db.scalars(select(Face).where(Face.person_id.is_(None), Face.ignored.is_(False))))
    assigned = assign_to_persons(db, free)
    created = cluster_unassigned(db)
    return {"dissolved": dissolved, "assigned": assigned, "created": created}


def merge_persons(db: Session, src: Person, dst: Person) -> None:
    """Move every face of src into dst, delete src, refresh dst's centroid.
    Reassign through the relationship (not the raw FK) so the faces leave
    src.faces before the delete — otherwise SQLAlchemy's dependency processing
    nulls their person_id when src is deleted."""
    for f in list(src.faces):
        f.person = dst
        f.similarity = None
    if dst.cover_face_id is None:
        dst.cover_face_id = src.cover_face_id
    db.delete(src)
    db.flush()
    recompute_centroid(db, dst)


def fix_cover(db: Session, person: Person) -> None:
    """Ensure cover_face_id points at a live member; pick the best otherwise."""
    members = [f for f in person.faces if not f.ignored]
    if any(f.id == person.cover_face_id for f in members):
        return
    person.cover_face_id = max(members, key=lambda f: f.det_score).id if members else None
