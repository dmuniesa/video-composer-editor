"""Opening a pre-multi-source database seeds a single Source pointing at the
project's original folder and back-fills every video's source_id."""
from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import db as dbm
from app.models import Base, Project, Source, Video


def test_legacy_db_seeds_source(tmp_path):
    footage = tmp_path / "trip"
    footage.mkdir()

    # Build a legacy-style DB by hand: a project + videos with no source rows
    # and source_id left NULL (as they were before the multi-source change).
    cache = dbm.cache_dir_for(footage)
    cache.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{cache / 'montage.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(Project(name="Trip", video_dir=str(footage.resolve())))
        s.add(Video(rel_path="a.mp4", filename="a.mp4", cache_key="k1"))
        s.add(Video(rel_path="sub/b.mp4", filename="b.mp4", cache_key="k2"))
        s.commit()
    engine.dispose()
    dbm._engines.pop(str(footage.resolve()), None)  # force a fresh open + migration

    # Opening through the normal path runs _seed_sources.
    with dbm.open_session(footage) as db:
        sources = list(db.scalars(select(Source)))
        assert len(sources) == 1
        assert sources[0].path == str(footage.resolve())
        videos = list(db.scalars(select(Video)))
        assert len(videos) == 2
        assert all(v.source_id == sources[0].id for v in videos)
