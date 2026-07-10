"""Orchestration: ties scanner/frames/gemini/audio_analysis to the job queue
and the database. All functions here are called from API handlers and run
their heavy parts as background jobs."""
from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from .. import db as dbm
from ..events import broadcaster
from ..models import Song, SongSection, Video, VideoAnalysis, VideoRating
from . import audio_analysis, frames, gemini, jobs, scanner


def video_cache(video_dir: Path, cache_key: str) -> Path:
    return dbm.cache_dir_for(video_dir) / cache_key


def scan_project(pid: str, video_dir: Path) -> dict:
    """Synchronously register video files, then queue per-video media jobs."""
    new_ids: list[int] = []
    with dbm.open_session(video_dir) as db:
        known = {v.rel_path: v for v in db.scalars(select(Video))}
        found = scanner.find_videos(video_dir)
        for path in found:
            rel = str(path.relative_to(video_dir))
            if rel in known:
                continue
            video = Video(
                rel_path=rel,
                filename=path.name,
                size=path.stat().st_size,
                cache_key=scanner.cache_key_for(rel),
                status="pending",
            )
            db.add(video)
            db.flush()
            db.add(VideoRating(video_id=video.id))
            new_ids.append(video.id)
        # Drop DB rows whose file disappeared.
        found_rels = {str(p.relative_to(video_dir)) for p in found}
        removed = 0
        for rel, video in known.items():
            if rel not in found_rels:
                db.delete(video)
                removed += 1
        db.commit()

    for vid in new_ids:
        queue_media_job(pid, video_dir, vid)
    return {"added": len(new_ids), "removed": removed, "total": len(found)}


def queue_media_job(pid: str, video_dir: Path, video_id: int) -> None:
    if jobs.has_active(pid, "media", video_id):
        return

    def work(job: jobs.Job) -> None:
        with dbm.open_session(video_dir) as db:
            video = db.get(Video, video_id)
            if video is None:
                return
            path = video_dir / video.rel_path
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

        queue_analysis_job(pid, video_dir, video_id)

    jobs.submit(pid, "media", f"media #{video_id}", work, pool="media", video_id=video_id)


def queue_analysis_job(pid: str, video_dir: Path, video_id: int, force: bool = False) -> bool:
    """Queue Gemini analysis for one video. Returns False when skipped."""
    if not gemini.agy_available():
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
            if not frame_paths:
                raise RuntimeError("no extracted frames to analyze")
            video.status = "analyzing"
            db.commit()
            broadcaster.publish(pid, "video", {"id": video_id})
            try:
                result = gemini.analyze_video_frames(frame_paths, workdir=cache)
                analysis = video.analysis or VideoAnalysis(video_id=video_id)
                analysis.description = result["description"]
                analysis.ai_score = result["score"]
                analysis.hashtags = result["hashtags"]
                analysis.raw_response = result["raw"]
                db.add(analysis)
                video.status = "ready"
                video.error = None
                db.commit()
            except Exception as exc:
                video.status = "error"
                video.error = f"AI analysis failed: {exc}"
                db.commit()
                raise
            finally:
                broadcaster.publish(pid, "video", {"id": video_id})

    jobs.submit(pid, "analyze", f"analyze #{video_id}", work, pool="ai", video_id=video_id)
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

                # Best-effort semantic labels from Gemini.
                if gemini.agy_available():
                    jobs.update(job, 0.8, "labeling sections (Gemini)")
                    try:
                        labels = gemini.label_sections(
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

    jobs.submit(pid, "song", "analyze song", work, pool="audio")
