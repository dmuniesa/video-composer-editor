"""Orchestration: ties scanner/frames/gemini/audio_analysis to the job queue
and the database. All functions here are called from API handlers and run
their heavy parts as background jobs."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select

from .. import db as dbm, settings
from ..events import broadcaster
from ..models import (
    ExcludedFile,
    Face,
    Person,
    Song,
    SongLyrics,
    SongSection,
    Source,
    Video,
    VideoAnalysis,
    VideoRating,
)
from . import ai, audio_analysis, faces, frames, jobs, lyrics, scanner

log = logging.getLogger(__name__)


def video_cache(video_dir: Path, cache_key: str) -> Path:
    return dbm.cache_dir_for(video_dir) / cache_key


def source_root(video: Video) -> Path:
    """Absolute root directory of the video's source. Falls back to '.' if the
    source row is somehow missing (should not happen after migration)."""
    return Path(video.source.path) if video.source else Path(".")


def scan_project(pid: str, video_dir: Path) -> dict:
    """Scan every source directory, register new video files and drop rows whose
    file disappeared, then queue per-video media jobs."""
    new_ids: list[int] = []
    added = removed = total = 0
    with dbm.open_session(video_dir) as db:
        sources = list(db.scalars(select(Source)))
        # Existing rows keyed per source so identical rel_paths in different
        # sources don't collide.
        known: dict[tuple[int, str], Video] = {
            (v.source_id, v.rel_path): v for v in db.scalars(select(Video))
        }
        # Tombstones for files the user deleted in Review; keep skipping them on
        # rescan so a deletion sticks.
        excluded: dict[tuple[int | None, str], ExcludedFile] = {
            (e.source_id, e.rel_path): e for e in db.scalars(select(ExcludedFile))
        }
        for source in sources:
            root = Path(source.path)
            if not root.is_dir():
                # Source moved/offline: leave its videos untouched (relink later).
                total += sum(1 for k in known if k[0] == source.id)
                continue
            found = scanner.find_videos(root)
            found_rels: set[str] = set()
            for path in found:
                rel = str(path.relative_to(root))
                found_rels.add(rel)
                if (source.id, rel) in excluded:
                    # User deleted this file; honor the tombstone, don't re-add.
                    continue
                total += 1
                if (source.id, rel) in known:
                    continue
                video = Video(
                    rel_path=rel,
                    source_id=source.id,
                    filename=path.name,
                    size=path.stat().st_size,
                    cache_key=scanner.cache_key_for(f"{source.id}/{rel}"),
                    status="pending",
                )
                db.add(video)
                db.flush()
                db.add(VideoRating(video_id=video.id))
                new_ids.append(video.id)
            # Drop DB rows of this source whose file disappeared.
            for (sid, rel), video in known.items():
                if sid == source.id and rel not in found_rels:
                    db.delete(video)
                    removed += 1
            # Drop tombstones of this source whose file is gone from disk: there
            # is nothing left to exclude, and if the file ever returns it should
            # be treated as new footage again.
            for (sid, rel), exc in excluded.items():
                if sid == source.id and rel not in found_rels:
                    db.delete(exc)
        added = len(new_ids)
        db.commit()

    for vid in new_ids:
        queue_media_job(pid, video_dir, vid)
    return {"added": added, "removed": removed, "total": total}


def queue_media_job(pid: str, video_dir: Path, video_id: int) -> None:
    if jobs.has_active(pid, "media", video_id):
        return

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            video = db.get(Video, video_id)
            if video is None:
                return
            path = source_root(video) / video.rel_path
            cache = video_cache(video_dir, video.cache_key)
            try:
                video.status = "extracting"
                db.commit()
                broadcaster.publish(pid, "video", {"id": video_id})

                probe = scanner.probe(path)
                video.duration = probe.duration
                video.fps = probe.fps
                video.width = probe.width
                video.height = probe.height
                video.codec = probe.codec
                video.shot_at = probe.shot_at
                video.meta = probe.meta
                db.commit()

                jobs.update(job, 0.1, "extracting frames")
                extracted = frames.extract_analysis_frames(path, probe.duration, cache)
                video.frame_count = len(extracted)
                jobs.update(job, 0.5, "thumbnail + filmstrip")
                frames.make_thumbnail(path, probe.duration, cache)
                frames.make_filmstrip(path, probe.duration, cache)
                if scanner.needs_proxy(probe):
                    jobs.update(job, 0.6, "transcoding proxy")
                    frames.make_proxy(path, cache)
                    video.has_proxy = True
                jobs.update(job, 0.7, "preview proxy")
                frames.make_preview(path, cache)
                # Separate clip-audio file (preview.mp3); optional — a missing
                # file just means the montage preview is silent for this clip.
                try:
                    jobs.update(job, 0.78, "clip audio")
                    frames.make_clip_audio(path, cache)
                except Exception as exc:  # noqa: BLE001 - clip audio is optional
                    log.info("clip audio extract failed for #%d: %s", video_id, exc)
                jobs.update(job, 0.85, "audio waveform")
                audio_analysis.compute_video_peaks(path, cache / "audio_peaks.json")
                video.status = "extracted"
                video.error = None
                db.commit()
            except Exception as exc:
                video.status = "error"
                video.error = str(exc)
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "video", {"id": video_id})

        # AI analysis is not triggered automatically: the clip stops at
        # "extracted" and the user chooses when to run it (Setup → "Analyze all
        # with AI") and which clips (Review → "Analyze selected"). This lets them
        # cull junk footage before spending AI calls on it.

    jobs.submit(pid, "media", f"media #{video_id}", work, pool="media", video_id=video_id)


def queue_analysis_job(pid: str, video_dir: Path, video_id: int, force: bool = False) -> bool:
    """Queue Gemini analysis for one video. Returns False when skipped."""
    if not ai.available():
        return False
    if jobs.has_active(pid, "analyze", video_id):
        return False
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, video_id)
        if video is None or video.status not in ("extracted", "ready", "error"):
            return False
        if video.analysis is not None and not force:
            return False

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            video = db.get(Video, video_id)
            if video is None:
                return
            cache = video_cache(video_dir, video.cache_key)
            frame_paths = sorted(cache.glob("frame_*.jpg"))
            # Video mode (agy only): attach the low-res preview.mp4 so the
            # model sees motion and can return highlight time ranges. Falls
            # back to frames when the provider/setting says so, the preview is
            # missing (project scanned before the rendition existed), or the
            # clip is too long to upload.
            video_file = None
            preview = cache / "preview.mp4"
            if (
                ai.provider() == "agy"
                and settings.get().analysis.agy_media == "video"
                and preview.is_file()
                and 0 < video.duration <= ai.VIDEO_ATTACH_MAX_S
            ):
                video_file = preview
            elif settings.get().analysis.agy_media == "video" and ai.provider() == "agy":
                log.info(
                    "analysis #%d: video mode unavailable (preview=%s, duration=%.1fs) — using frames",
                    video_id,
                    preview.is_file(),
                    video.duration,
                )
            if video_file is None and not frame_paths:
                raise RuntimeError("no extracted frames to analyze")
            # Names already identified by face recognition, so the description
            # can refer to people by name. Empty when faces haven't run or
            # nobody is named yet; a later re-analyze picks names up.
            people: list[str] = []
            if settings.get().analysis.people_in_prompt:
                people = sorted(
                    {
                        name
                        for (name,) in db.execute(
                            select(Person.name)
                            .join(Face, Face.person_id == Person.id)
                            .where(
                                Face.video_id == video_id,
                                Face.ignored.is_(False),
                                Person.name != "",
                                Person.hidden.is_(False),
                            )
                        )
                    }
                )
            video.status = "analyzing"
            db.commit()
            broadcaster.publish(pid, "video", {"id": video_id})
            try:
                result = ai.analyze_clip(
                    frame_paths,
                    workdir=cache,
                    people=people,
                    video_file=video_file,
                    duration=video.duration,
                )
                analysis = video.analysis or VideoAnalysis(video_id=video_id)
                analysis.description = result["description"]
                analysis.ai_score = result["score"]
                analysis.hashtags = result["hashtags"]
                analysis.raw_response = result["raw"]
                analysis.mood = result["mood"]
                analysis.energy = result["energy"]
                analysis.scene = result["scene"]
                analysis.time_of_day = result["time_of_day"]
                analysis.shot_type = result["shot_type"]
                analysis.highlights = result["highlights"]
                db.add(analysis)
                video.status = "ready"
                video.error = None
                db.commit()
            except Exception as exc:
                # If the failure happened inside commit() the session is in a
                # rolled-back state; clear it or the error commit below raises
                # PendingRollbackError and the clip stays stuck in "analyzing".
                db.rollback()
                video.status = "error"
                video.error = f"AI analysis failed: {exc}"
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "video", {"id": video_id})

    jobs.submit(pid, "analyze", f"analyze #{video_id}", work, pool="ai", video_id=video_id)
    return True


def queue_faces_job(pid: str, video_dir: Path, video_id: int, force: bool = False) -> bool:
    """Queue face detection for one video. Returns False when skipped."""
    if not faces.available():
        return False
    if jobs.has_active(pid, "faces", video_id):
        return False
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, video_id)
        if video is None or video.status not in ("extracted", "ready"):
            return False
        if video.faces_status == "done" and not force:
            return False

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            video = db.get(Video, video_id)
            if video is None:
                return
            cache = video_cache(video_dir, video.cache_key)
            video.faces_status = "detecting"
            db.commit()
            broadcaster.publish(pid, "video", {"id": video_id})
            try:
                # First run downloads the model pack (~30-280 MB).
                jobs.update(job, 0.05, "loading face model (first run downloads it)")
                count = faces.detect_video(
                    db, video, cache, progress=lambda pct, msg: jobs.update(job, pct, msg)
                )
                jobs.update(job, 0.95, "clustering")
                faces.cluster_unassigned(db)
                video.faces_status = "done"
                db.commit()
                jobs.update(job, 1.0, f"{count} face(s)")
            except Exception:
                db.rollback()
                video.faces_status = "error"
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "video", {"id": video_id})
                broadcaster.publish(pid, "people", {})

    jobs.submit(pid, "faces", f"faces #{video_id}", work, pool="faces", video_id=video_id)
    return True


def queue_recluster_job(pid: str, video_dir: Path) -> bool:
    """Re-cluster unnamed faces in the background (same pool as detection so
    it never runs concurrently with a detect job touching the same rows)."""
    if jobs.has_active(pid, "recluster"):
        return False

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            jobs.update(job, 0.3, "re-clustering faces")
            result = faces.recluster(db)
            db.commit()
            jobs.update(job, 1.0, f"{result['created']} group(s)")
        broadcaster.publish(pid, "people", {})

    jobs.submit(pid, "recluster", "re-cluster people", work, pool="faces")
    return True


def set_song(pid: str, video_dir: Path, song_path: Path) -> None:
    from ..models import Project

    with dbm.open_session(video_dir) as db:
        for old in db.scalars(select(Song)):
            db.delete(old)
        db.add(Song(path=str(song_path.resolve()), status="pending"))
        project = db.scalar(select(Project))
        if project is not None:
            project.song_path = str(song_path.resolve())
        db.commit()
    queue_song_job(pid, video_dir)


def queue_song_job(pid: str, video_dir: Path) -> None:
    if jobs.has_active(pid, "song"):
        return

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            song = db.scalar(select(Song))
            if song is None:
                return
            path = Path(song.path)
            try:
                song.status = "analyzing"
                db.commit()
                broadcaster.publish(pid, "song", {})

                jobs.update(job, 0.1, "waveform peaks")
                peaks_path = dbm.cache_dir_for(video_dir) / "song_peaks.json"
                audio_analysis.compute_peaks(path, peaks_path)

                jobs.update(job, 0.3, "beats + sections (librosa)")
                result = audio_analysis.analyze(path)
                song.duration = result.duration
                song.bpm = result.bpm
                song.beats_json = json.dumps(result.beats)
                song.downbeats_json = json.dumps(result.downbeats)
                for old in list(song.sections):
                    db.delete(old)
                for s in result.sections:
                    db.add(
                        SongSection(
                            song_id=song.id,
                            start=s["start"],
                            end=s["end"],
                            energy=s["energy"],
                            label="",
                            source="auto",
                        )
                    )
                song.status = "ready"
                song.error = None
                db.commit()

                # Best-effort semantic labels from the AI provider.
                if ai.available():
                    jobs.update(job, 0.8, "labeling sections (AI)")
                    try:
                        # On re-analysis a previous transcription may already
                        # exist; its lyrics sharpen the section labels.
                        if song.lyrics is not None and song.lyrics.status == "ready":
                            lyrics.attach_hints(result.sections, song.lyrics.segments)
                        labels = ai.label_sections(
                            result.duration, result.bpm, result.sections
                        )
                        # The relationship still caches the deleted sections;
                        # reload it so labels land on the fresh rows.
                        db.expire(song, ["sections"])
                        for section, label in zip(song.sections, labels):
                            if label:
                                section.label = label
                                section.source = "ai"
                        db.commit()
                    except Exception as exc:  # noqa: BLE001 - labels are optional
                        jobs.update(job, 0.9, f"section labeling skipped: {exc}")
            except Exception as exc:
                song.status = "error"
                song.error = str(exc)
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "song", {})

        queue_lyrics_job(pid, video_dir)

    jobs.submit(pid, "song", "analyze song", work, pool="audio")


def queue_lyrics_job(pid: str, video_dir: Path, force: bool = False) -> bool:
    """Queue the lyrics transcription for the song (local Whisper or Gemini
    via agy, per Settings). Returns False when skipped (disabled in Settings,
    no engine available, already done...)."""
    conf = settings.get().lyrics
    if not conf.enabled or not lyrics.available():
        return False
    if jobs.has_active(pid, "lyrics"):
        return False
    with dbm.open_session(video_dir) as db:
        song = db.scalar(select(Song))
        if song is None or song.status != "ready":
            return False
        existing = song.lyrics
        if existing is not None and existing.status == "ready" and not force:
            return False

    def work(job: jobs.Job) -> None:
        conf = settings.get().lyrics
        with dbm.open_session(video_dir) as db:
            song = db.scalar(select(Song))
            if song is None:
                return
            row = song.lyrics or SongLyrics(song_id=song.id)
            row.status = "transcribing"
            row.error = None
            engine = lyrics.provider()
            row.model = "gemini (agy)" if engine == "agy" else f"whisper {conf.whisper_model}"
            db.add(row)
            db.commit()
            broadcaster.publish(pid, "song", {})
            try:
                jobs.update(job, 0.1, f"transcribing lyrics ({row.model})")
                result = lyrics.transcribe(
                    Path(song.path), conf.whisper_model, conf.language
                )
                row.language = result["language"]
                row.segments_json = json.dumps(result["segments"], ensure_ascii=False)
                row.status = "ready"
                db.commit()
            except Exception as exc:
                row.status = "error"
                row.error = str(exc)
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "song", {})

    jobs.submit(pid, "lyrics", "transcribe lyrics", work, pool="audio")
    return True
