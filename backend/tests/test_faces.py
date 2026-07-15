"""People detection: pure clustering/matching logic with synthetic embeddings
(no insightface needed), plus the people API surface with detection faked."""
from __future__ import annotations

import shutil

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import db as dbm
from app.main import app
from app.models import Face, Person, Video
from app.services import faces


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client, tmp_path, sample_video):
    videos = tmp_path / "trip"
    videos.mkdir()
    shutil.copy(sample_video, videos / "beach.mp4")
    shutil.copy(sample_video, videos / "dinner.mp4")
    res = client.post("/api/projects", json={"video_dir": str(videos)})
    assert res.status_code == 200, res.text
    return res.json()["id"], videos


def _vec(direction: int, dims: int = 8, noise: float = 0.0, seed: int = 0) -> np.ndarray:
    """Unit vector along an axis, optionally with deterministic noise — noisy
    copies of the same direction stay far above the clustering threshold."""
    v = np.zeros(dims, dtype=np.float32)
    v[direction] = 1.0
    if noise:
        rng = np.random.default_rng(seed)
        v = v + rng.normal(0, noise, dims).astype(np.float32)
    return faces.normalize(v)


def _add_video(db, filename: str) -> Video:
    v = Video(rel_path=filename, filename=filename, cache_key=filename, status="extracted")
    db.add(v)
    db.flush()
    return v


def _add_face(db, video: Video, emb: np.ndarray, score: float = 0.9, **kw) -> Face:
    f = Face(
        video_id=video.id,
        frame_index=1,
        t=1.0,
        det_score=score,
        embedding=faces.emb_to_blob(emb),
        **kw,
    )
    db.add(f)
    db.flush()
    return f


def test_blob_round_trip():
    v = _vec(3, noise=0.2, seed=1)
    out = faces.blob_to_emb(faces.emb_to_blob(v))
    assert out.dtype == np.float32
    assert np.allclose(out, v, atol=1e-6)
    assert pytest.approx(1.0, abs=1e-5) == float(np.linalg.norm(out))


def test_cluster_unassigned_groups_similar_faces(tmp_path):
    with dbm.open_session(tmp_path) as db:
        v1 = _add_video(db, "a.mp4")
        v2 = _add_video(db, "b.mp4")
        # Person A in both videos (noisy copies), person B once.
        _add_face(db, v1, _vec(0, noise=0.05, seed=1), score=0.95)
        _add_face(db, v2, _vec(0, noise=0.05, seed=2), score=0.8)
        _add_face(db, v1, _vec(1), score=0.9)
        created = faces.cluster_unassigned(db)
        db.commit()

        assert created == 2
        persons = list(db.scalars(select(Person)))
        assert sorted(len([f for f in p.faces if not f.ignored]) for p in persons) == [1, 2]
        for p in persons:
            assert p.name == ""
            assert p.centroid is not None
            assert p.cover_face_id in {f.id for f in p.faces}
        big = max(persons, key=lambda p: len(p.faces))
        assert {f.video_id for f in big.faces} == {v1.id, v2.id}


def test_assign_matches_named_person_and_recluster_keeps_names(tmp_path):
    with dbm.open_session(tmp_path) as db:
        v1 = _add_video(db, "a.mp4")
        v2 = _add_video(db, "b.mp4")
        f1 = _add_face(db, v1, _vec(0, noise=0.05, seed=1))
        faces.cluster_unassigned(db)
        ana = db.scalar(select(Person))
        ana.name = "Ana"
        db.commit()

        # New detection in another video: same person → auto-assigned.
        f2 = _add_face(db, v2, _vec(0, noise=0.05, seed=2))
        stranger = _add_face(db, v2, _vec(1))
        assigned = faces.assign_to_persons(db, [f2, stranger])
        db.commit()
        assert assigned == 1
        assert f2.person_id == ana.id
        assert f2.similarity is not None and f2.similarity >= faces.SIM_ASSIGN
        assert stranger.person_id is None

        # Re-cluster: the stranger gets an unnamed cluster; Ana survives intact.
        result = faces.recluster(db)
        db.commit()
        assert result["created"] == 1
        assert f1.person_id == ana.id and f2.person_id == ana.id
        names = {p.name for p in db.scalars(select(Person))}
        assert names == {"Ana", ""}


def test_merge_moves_faces_and_recomputes(tmp_path):
    with dbm.open_session(tmp_path) as db:
        v1 = _add_video(db, "a.mp4")
        fa = _add_face(db, v1, _vec(0))
        fb = _add_face(db, v1, _vec(1))
        faces.cluster_unassigned(db)
        db.commit()
        a, b = list(db.scalars(select(Person)))
        faces.merge_persons(db, a, b)
        db.commit()

        persons = list(db.scalars(select(Person)))
        assert len(persons) == 1
        assert {f.id for f in persons[0].faces} == {fa.id, fb.id}
        # Centroid is the normalized mean of both directions.
        centroid = faces.blob_to_emb(persons[0].centroid)
        assert pytest.approx(centroid[0], abs=1e-5) == pytest.approx(centroid[1], abs=1e-5)


def test_rename_to_existing_name_merges(client, project):
    pid, videos_dir = project
    client.post(f"/api/projects/{pid}/scan")
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        _add_face(db, video, _vec(0))
        _add_face(db, video, _vec(1))
        faces.cluster_unassigned(db)
        db.commit()

    listing = client.get(f"/api/projects/{pid}/people").json()
    a, b = listing["persons"]
    client.patch(f"/api/projects/{pid}/people/{a['id']}", json={"name": "Ana"})
    # Same name (different capitalization) on the other cluster → auto-merge.
    res = client.patch(f"/api/projects/{pid}/people/{b['id']}", json={"name": "ana"})
    assert res.status_code == 200
    merged = res.json()
    assert merged["id"] == a["id"]
    assert merged["name"] == "ana"  # keeps the freshly typed spelling
    assert merged["face_count"] == 2
    listing = client.get(f"/api/projects/{pid}/people").json()
    assert len(listing["persons"]) == 1


def test_set_cover_face(client, project):
    pid, videos_dir = project
    client.post(f"/api/projects/{pid}/scan")
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        _add_face(db, video, _vec(0, noise=0.05, seed=1), score=0.95)
        f2 = _add_face(db, video, _vec(0, noise=0.05, seed=2), score=0.7)
        faces.cluster_unassigned(db)
        db.commit()
        person_id = f2.person_id
        f2_id = f2.id

    person = client.get(f"/api/projects/{pid}/people").json()["persons"][0]
    assert person["cover_face_id"] != f2_id  # cover defaults to the best score
    res = client.patch(
        f"/api/projects/{pid}/people/{person_id}", json={"cover_face_id": f2_id}
    )
    assert res.status_code == 200
    assert res.json()["cover_face_id"] == f2_id
    # A face of another person is rejected.
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        stranger = _add_face(db, video, _vec(2))
        db.commit()
        stranger_id = stranger.id
    res = client.patch(
        f"/api/projects/{pid}/people/{person_id}", json={"cover_face_id": stranger_id}
    )
    assert res.status_code == 400


def test_hidden_person_leaves_chips_but_keeps_faces(client, project):
    pid, videos_dir = project
    client.post(f"/api/projects/{pid}/scan")
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        _add_face(db, video, _vec(0))
        faces.cluster_unassigned(db)
        db.commit()

    person = client.get(f"/api/projects/{pid}/people").json()["persons"][0]
    client.patch(f"/api/projects/{pid}/people/{person['id']}", json={"name": "Extra"})
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert any(v["people"] for v in videos)

    res = client.patch(f"/api/projects/{pid}/people/{person['id']}", json={"hidden": True})
    assert res.json()["hidden"] is True
    # Gone from the video chips, still listed (flagged) with its faces intact.
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert all(v["people"] == [] for v in videos)
    listing = client.get(f"/api/projects/{pid}/people").json()["persons"]
    assert listing[0]["hidden"] is True and listing[0]["face_count"] == 1

    # Renaming another cluster to the same name unhides (signals interest).
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        _add_face(db, video, _vec(0, noise=0.05, seed=3))
        faces.cluster_unassigned(db)
        db.commit()
    listing = client.get(f"/api/projects/{pid}/people").json()["persons"]
    fresh = next((p for p in listing if not p["name"]), None)
    if fresh is not None:  # the new face may have auto-merged already
        res = client.patch(f"/api/projects/{pid}/people/{fresh['id']}", json={"name": "extra"})
        assert res.json()["hidden"] is False


def test_assignment_learns_from_confirmed_faces(tmp_path):
    """A borderline face misses when the person has one seed face, but matches
    once the person holds a nearer confirmed face (nearest-neighbor growth)."""
    dims = 8
    seed = faces.normalize(np.eye(dims, dtype=np.float32)[0])
    # Far enough from the seed (cos ~0.41) to miss SIM_ASSIGN against it alone.
    borderline = faces.normalize(seed + 2.2 * np.eye(dims, dtype=np.float32)[1])
    assert faces.cosine(seed, borderline) < faces.SIM_ASSIGN
    # A confirmed intermediate face sits between the two.
    intermediate = faces.normalize(seed + borderline)
    assert faces.cosine(intermediate, borderline) >= faces.SIM_ASSIGN

    with dbm.open_session(tmp_path) as db:
        v = _add_video(db, "a.mp4")
        _add_face(db, v, seed)
        faces.cluster_unassigned(db)
        db.commit()

        hard = _add_face(db, v, borderline)
        assert faces.assign_to_persons(db, [hard]) == 0  # not yet

        confirmed = _add_face(db, v, intermediate)
        person = db.scalar(select(Person))
        confirmed.person_id = person.id  # user confirms it manually
        db.flush()
        faces.recompute_centroid(db, person)

        assert faces.assign_to_persons(db, [hard]) == 1  # learned
        assert hard.person_id == person.id


def test_detect_endpoint_unavailable_returns_409(client, project, monkeypatch):
    pid, _ = project
    monkeypatch.setattr(faces, "_checked", True)
    monkeypatch.setattr(faces, "_import_error", "No module named 'insightface'")
    res = client.post(f"/api/projects/{pid}/faces/detect", json={})
    assert res.status_code == 409
    assert "insightface" in res.json()["detail"]

    listing = client.get(f"/api/projects/{pid}/people").json()
    assert listing["available"] is False
    assert listing["persons"] == []


def test_people_api_flow(client, project, monkeypatch):
    """Rename / merge / face corrections / video people over canned faces."""
    pid, videos_dir = project
    client.post(f"/api/projects/{pid}/scan")

    with dbm.open_session(videos_dir) as db:
        vids = list(db.scalars(select(Video).order_by(Video.filename)))
        _add_face(db, vids[0], _vec(0, noise=0.05, seed=1))
        _add_face(db, vids[1], _vec(0, noise=0.05, seed=2))
        _add_face(db, vids[1], _vec(1))
        faces.cluster_unassigned(db)
        db.commit()

    listing = client.get(f"/api/projects/{pid}/people").json()
    assert len(listing["persons"]) == 2
    big = listing["persons"][0]  # unnamed sorted by face_count desc
    assert big["face_count"] == 2 and len(big["videos"]) == 2

    # Name the 2-face cluster; videos now list her.
    res = client.patch(f"/api/projects/{pid}/people/{big['id']}", json={"name": "Ana"})
    assert res.json()["name"] == "Ana"
    videos = client.get(f"/api/projects/{pid}/videos").json()
    assert all(v["people"] == [{"id": big["id"], "name": "Ana"}] for v in videos)

    # Merge the singleton into Ana.
    other = next(p for p in listing["persons"] if p["id"] != big["id"])
    res = client.post(
        f"/api/projects/{pid}/people/{other['id']}/merge", json={"into_id": big["id"]}
    )
    assert res.status_code == 200
    assert res.json()["face_count"] == 3

    # Detach one face, then ignore it: counts drop, centroid survives.
    ana_faces = client.get(f"/api/projects/{pid}/people/{big['id']}/faces").json()
    assert len(ana_faces) == 3
    res = client.patch(
        f"/api/projects/{pid}/faces/{ana_faces[0]['id']}",
        json={"person_id": None, "ignored": True},
    )
    assert res.json()["person_id"] is None and res.json()["ignored"] is True
    listing = client.get(f"/api/projects/{pid}/people").json()
    assert listing["persons"][0]["face_count"] == 2

    # Delete the person: faces are freed, not gone.
    res = client.delete(f"/api/projects/{pid}/people/{big['id']}")
    assert res.json()["ok"] is True
    with dbm.open_session(videos_dir) as db:
        assert db.scalar(select(Person)) is None
        remaining = list(db.scalars(select(Face)))
        assert len(remaining) == 3
        assert all(f.person_id is None for f in remaining)


def test_video_delete_cascades_faces(client, project):
    pid, videos_dir = project
    client.post(f"/api/projects/{pid}/scan")
    with dbm.open_session(videos_dir) as db:
        video = db.scalar(select(Video))
        _add_face(db, video, _vec(0))
        db.commit()
        vid = video.id

    res = client.delete(f"/api/projects/{pid}/videos/{vid}")
    assert res.json()["ok"] is True
    with dbm.open_session(videos_dir) as db:
        assert db.scalar(select(Face)) is None
