"""SQLAlchemy ORM models. One SQLite database per project, stored in
<video_dir>/.montage-cache/montage.db so a project travels with its footage."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    video_dir: Mapped[str] = mapped_column(String)
    song_path: Mapped[str | None] = mapped_column(String, nullable=True)
    composition_fps: Mapped[float] = mapped_column(Float, default=25.0)
    composition_width: Mapped[int] = mapped_column(Integer, default=1920)
    composition_height: Mapped[int] = mapped_column(Integer, default=1080)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Video(Base):
    __tablename__ = "video"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rel_path: Mapped[str] = mapped_column(String, unique=True)
    filename: Mapped[str] = mapped_column(String)
    duration: Mapped[float] = mapped_column(Float, default=0.0)
    fps: Mapped[float] = mapped_column(Float, default=0.0)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    codec: Mapped[str] = mapped_column(String, default="")
    size: Mapped[int] = mapped_column(Integer, default=0)
    shot_at: Mapped[str | None] = mapped_column(String, nullable=True)
    # cache_key names this video's folder inside .montage-cache/
    cache_key: Mapped[str] = mapped_column(String, default="")
    # pending -> extracting -> extracted -> analyzing -> ready | error
    status: Mapped[str] = mapped_column(String, default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_proxy: Mapped[bool] = mapped_column(Boolean, default=False)
    frame_count: Mapped[int] = mapped_column(Integer, default=0)

    analysis: Mapped[VideoAnalysis | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    rating: Mapped[VideoRating | None] = relationship(
        back_populates="video", cascade="all, delete-orphan", uselist=False
    )
    ranges: Mapped[list[VideoRange]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="VideoRange.t_in"
    )


class VideoAnalysis(Base):
    __tablename__ = "video_analysis"

    video_id: Mapped[int] = mapped_column(ForeignKey("video.id"), primary_key=True)
    description: Mapped[str] = mapped_column(Text, default="")
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    hashtags_json: Mapped[str] = mapped_column(Text, default="[]")
    raw_response: Mapped[str] = mapped_column(Text, default="")

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

    track: Mapped[Track] = relationship(back_populates="clips")
    video: Mapped[Video] = relationship()

    @property
    def duration(self) -> float:
        """Length the clip occupies on the timeline (source range / speed)."""
        return (self.source_out - self.source_in) / (self.speed or 1.0)
