"""SQLAlchemy ORM models. One SQLite database per project, stored in
<project_dir>/.montage-cache/montage.db, where <project_dir> is the storage
folder the user picked for the project (decoupled from the footage, which lives
in one or more Source directories)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    # Storage folder of the project: where montage.db and all cache live. It is
    # chosen by the user and decoupled from the footage (see Source below).
    video_dir: Mapped[str] = mapped_column(String)
    song_path: Mapped[str | None] = mapped_column(String, nullable=True)
    composition_fps: Mapped[float] = mapped_column(Float, default=25.0)
    composition_width: Mapped[int] = mapped_column(Integer, default=1920)
    composition_height: Mapped[int] = mapped_column(Integer, default=1080)
    # When true, each clip's audio is gain-shifted by its stored norm_gain_db so
    # every clip lands at normalize_target_lufs (EBU R128 loudness equalisation).
    normalize_audio: Mapped[bool] = mapped_column(Boolean, default=False)
    normalize_target_lufs: Mapped[float] = mapped_column(Float, default=-16.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Source(Base):
    """A footage directory attached to the project. A project has zero or more
    sources; each video belongs to exactly one. Sources can be added, removed
    and re-pointed (relink) freely without touching the project's storage."""

    __tablename__ = "source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String)
    label: Mapped[str] = mapped_column(String, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    videos: Mapped[list[Video]] = relationship(back_populates="source")


class Video(Base):
    __tablename__ = "video"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # rel_path is relative to this video's source root. Uniqueness is
    # (source_id, rel_path); enforced in the scanner, not by the DB, so two
    # sources may hold the same relative path.
    rel_path: Mapped[str] = mapped_column(String)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    codec: Mapped[str] = mapped_column(String, default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    shot_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # Curated ffprobe container tags (camera make/model, lens, software,
    # location, plus any other tags). JSON object, "{}" when none. New column,
    # back-filled onto legacy databases by db._ensure_columns.
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    # cache_key names this video's folder inside .montage-cache/
    cache_key: Mapped[str] = mapped_column(String, default="")
    # pending -> extracting -> extracted -> analyzing -> ready | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)
    # none -> detecting -> done | error (independent of the media/AI pipeline)
    faces_status: Mapped[str] = mapped_column(String, default="none")

    @property
    def meta(self) -> dict:
        try:
            return json.loads(self.meta_json)
        except (ValueError, TypeError):
            return {}

    @meta.setter
    def meta(self, value: dict) -> None:
        self.meta_json = json.dumps(value)

    source: Mapped[Source | None] = relationship(back_populates="videos")
    analysis: Mapped[VideoAnalysis | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    rating: Mapped[VideoRating | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    ranges: Mapped[list[VideoRange]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="VideoRange.t_in"
    )
    faces: Mapped[list[Face]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )


class ExcludedFile(Base):
    """Tombstone for a video the user deleted in Review. Records the
    (source_id, rel_path) of the file so a later rescan of that source skips it
    instead of re-adding the row (the source file on disk is never touched).
    Dropped automatically when the underlying file disappears from disk (nothing
    left to exclude), or explicitly when the user restores it. New table, so
    create_all adds it to existing project databases without a migration."""

    __tablename__ = "excluded_file"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("source.id"), nullable=True)
    # rel_path is relative to the source root, same convention as Video.rel_path.
    rel_path: Mapped[str] = mapped_column(String)
    filename: Mapped[str] = mapped_column(String, default="")
    excluded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class VideoAnalysis(Base):
    __tablename__ = "video_analysis"

    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hashtags_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_response: Mapped[str] = mapped_column(Text, default="")
    # Optional analysis aspects (each toggleable in Settings). New columns,
    # back-filled onto legacy databases by db._ensure_columns; NULL/"[]" on
    # rows analyzed before the aspect existed or while it was disabled.
    mood_json: Mapped[str] = mapped_column(Text, default="[]")  # ["happy","funny"]
    energy: Mapped[str | None] = mapped_column(String, nullable=True)  # low|medium|high
    scene: Mapped[str | None] = mapped_column(String, nullable=True)  # "beach"
    time_of_day: Mapped[str | None] = mapped_column(String, nullable=True)  # day|sunrise|sunset|night
    shot_type: Mapped[str | None] = mapped_column(String, nullable=True)  # drone|wide|close-up|...
    # AI-suggested best moments as time ranges (video-mode analysis only):
    # [{"t_in": 2.0, "t_out": 4.0, "reason": "the boy leans into the camera"}]
    highlights_json: Mapped[str] = mapped_column(Text, default="[]")

    video: Mapped[Video] = relationship(back_populates="analysis")

    @property
    def hashtags(self) -> list[str]:
        try:
            return json.loads(self.hashtags_json)
        except (ValueError, TypeError):
            return []

    @hashtags.setter
    def hashtags(self, value: list[str]) -> None:
        self.hashtags_json = json.dumps(value)

    @property
    def mood(self) -> list[str]:
        try:
            return json.loads(self.mood_json)
        except (ValueError, TypeError):
            return []

    @mood.setter
    def mood(self, value: list[str]) -> None:
        self.mood_json = json.dumps(value)

    @property
    def highlights(self) -> list[dict]:
        try:
            return json.loads(self.highlights_json)
        except (ValueError, TypeError):
            return []

    @highlights.setter
    def highlights(self, value: list[dict]) -> None:
        self.highlights_json = json.dumps(value)


class VideoRating(Base):
    __tablename__ = "video_rating"

    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"), primary_key=True)
    stars: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[bool] = mapped_column(Boolean, default=False)

    video: Mapped[Video] = relationship(back_populates="rating")


class VideoRange(Base):
    __tablename__ = "video_range"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"))
    t_in: Mapped[float] = mapped_column(Float)
    t_out: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String, default="")

    video: Mapped[Video] = relationship(back_populates="ranges")


class Person(Base):
    """A person appearing in the project's footage. Created automatically by
    clustering detected faces; the user gives it a name (name == "" means an
    unnamed cluster awaiting review). Once named, new faces matching the
    centroid are auto-assigned across videos."""

    __tablename__ = "person"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    # Soft reference (no FK) to the face used as the card cover; cleared by the
    # API when that face is detached/ignored.
    cover_face_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # L2-normalized mean of the member embeddings, float32 little-endian.
    centroid: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # User marked this person as not interesting: kept (so their faces stay
    # assigned and keep absorbing new detections) but tucked away in the UI
    # and excluded from Review chips, the composer and MCP.
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    faces: Mapped[list[Face]] = relationship(back_populates="person")


class Face(Base):
    """One detected face in one sampled frame of a video. The bbox is
    normalized to the frame (0-1) so it survives resolution changes; the
    embedding is an L2-normalized float32 vector (cosine similarity == dot)."""

    __tablename__ = "face"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"))
    frame_index: Mapped[int] = mapped_column(Integer)
    t: Mapped[float] = mapped_column(Float, default=0.0)
    x: Mapped[float] = mapped_column(Float, default=0.0)
    y: Mapped[float] = mapped_column(Float, default=0.0)
    w: Mapped[float] = mapped_column(Float, default=0.0)
    h: Mapped[float] = mapped_column(Float, default=0.0)
    det_score: Mapped[float] = mapped_column(Float, default=0.0)
    embedding: Mapped[bytes] = mapped_column(LargeBinary)
    person_id: Mapped[int | None] = mapped_column(ForeignKey("person.id"), nullable=True)
    # Cosine similarity to the person centroid at auto-assign time; None for
    # manual assignments and cluster seeds.
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    # True = user marked it as not-a-person/false positive; excluded everywhere.
    ignored: Mapped[bool] = mapped_column(Boolean, default=False)

    video: Mapped[Video] = relationship(back_populates="faces")
    person: Mapped[Person | None] = relationship(back_populates="faces")


class Song(Base):
    __tablename__ = "song"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    path: Mapped[str] = mapped_column(String)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True)
    beats_json: Mapped[str] = mapped_column(Text, default="[]")
    downbeats_json: Mapped[str] = mapped_column(Text, default="[]")
    # pending -> analyzing -> ready | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Main audio lane controls (the song). New columns, back-filled by
    # db._ensure_columns onto legacy databases.
    muted: Mapped[bool] = mapped_column(Boolean, default=False)
    volume: Mapped[float] = mapped_column(Float, default=1.0)  # linear gain 0..1

    sections: Mapped[list[SongSection]] = relationship(
        back_populates="song", cascade="all, delete-orphan", order_by="SongSection.start"
    )
    lyrics: Mapped[SongLyrics | None] = relationship(
        back_populates="song", cascade="all, delete-orphan", uselist=False
    )

    @property
    def beats(self) -> list[float]:
        try:
            return json.loads(self.beats_json)
        except (ValueError, TypeError):
            return []

    @property
    def downbeats(self) -> list[float]:
        try:
            return json.loads(self.downbeats_json)
        except (ValueError, TypeError):
            return []


class SongLyrics(Base):
    """Whisper transcription of the song, one row per song. Lives in its own
    table (not columns on Song) so existing project databases keep working
    without a migration — create_all only adds new tables."""

    __tablename__ = "song_lyrics"

    song_id: Mapped[int] = mapped_column(ForeignKey("song.id"), primary_key=True)
    # pending -> transcribing -> ready | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str] = mapped_column(String, default="")
    model: Mapped[str] = mapped_column(String, default="")
    # [{"start": s, "end": s, "text": "..."}] — one item per sung line
    segments_json: Mapped[str] = mapped_column(Text, default="[]")

    song: Mapped[Song] = relationship(back_populates="lyrics")

    @property
    def segments(self) -> list[dict]:
        try:
            return json.loads(self.segments_json)
        except (ValueError, TypeError):
            return []


class SongSection(Base):
    __tablename__ = "song_section"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(ForeignKey("song.id"))
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    label: Mapped[str] = mapped_column(String, default="")
    source: Mapped[str] = mapped_column(String, default="auto")  # auto | ai | user
    energy: Mapped[float] = mapped_column(Float, default=0.0)

    song: Mapped[Song] = relationship(back_populates="sections")


class Track(Base):
    __tablename__ = "track"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    index: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String, default="")
    # Clip-audio lane controls: the original audio of this track's clips is laid
    # on its own stereo audio lane in the montage and export. New columns,
    # back-filled onto legacy databases by db._ensure_columns.
    audio_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_volume: Mapped[float] = mapped_column(Float, default=1.0)  # linear gain 0..1

    clips: Mapped[list[TimelineClip]] = relationship(
        back_populates="track", cascade="all, delete-orphan", order_by="TimelineClip.timeline_start"
    )


class TimelineClip(Base):
    __tablename__ = "timeline_clip"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    track_id: Mapped[int] = mapped_column(ForeignKey("track.id"))
    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"))
    timeline_start: Mapped[float] = mapped_column(Float)
    source_in: Mapped[float] = mapped_column(Float)
    source_out: Mapped[float] = mapped_column(Float)
    # playback rate: 0.5 = slow motion at half speed, 2.0 = double speed
    speed: Mapped[float] = mapped_column(Float, default=1.0)
    placed_by: Mapped[str] = mapped_column(String, default="user")  # user | claude | agy | openai
    # User per-clip audio offset (dB) set via the clip's right-click menu; applied
    # on top of normalisation. 0 == no change.
    audio_gain_db: Mapped[float] = mapped_column(Float, default=0.0)
    # Auto-computed gain (dB) to reach Project.normalize_target_lufs, set by the
    # "normalise audio" action (loudnorm measurement). Only applied when the
    # project's normalize_audio flag is on.
    norm_gain_db: Mapped[float] = mapped_column(Float, default=0.0)

    track: Mapped[Track] = relationship(back_populates="clips")
    video: Mapped[Video] = relationship()

    @property
    def duration(self) -> float:
        """Length the clip occupies on the timeline (source range / speed)."""
        return (self.source_out - self.source_in) / (self.speed or 1.0)
