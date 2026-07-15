"""People (face) detection API: trigger detection, list persons and faces,
name/merge/dissolve persons and correct individual face assignments."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from .. import db as dbm
from ..events import broadcaster
from ..models import Face, Person, Video
from ..services import faces, pipeline
from .deps import resolve_project

router = APIRouter()


def _face_dict(f: Face) -> dict:
    return {
        "id": f.id,
        "video_id": f.video_id,
        "filename": f.video.filename if f.video else "",
        "frame_index": f.frame_index,
        "t": f.t,
        "x": f.x,
        "y": f.y,
        "w": f.w,
        "h": f.h,
        "det_score": f.det_score,
        "similarity": f.similarity,
        "person_id": f.person_id,
        "ignored": f.ignored,
    }


def _person_dict(db, p: Person) -> dict:
    members = [f for f in p.faces if not f.ignored]
    video_ids = sorted({f.video_id for f in members})
    filenames = {
        v.id: v.filename
        for v in db.scalars(select(Video).where(Video.id.in_(video_ids)))
    } if video_ids else {}
    return {
        "id": p.id,
        "name": p.name,
        "cover_face_id": p.cover_face_id,
        "hidden": p.hidden,
        "face_count": len(members),
        "videos": [{"id": vid, "filename": filenames.get(vid, "")} for vid in video_ids],
    }


@router.get("/projects/{pid}/people")
def people_list(pid: str) -> dict:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        persons = list(db.scalars(select(Person)))
        items = [_person_dict(db, p) for p in persons]
    # Named first (alphabetical), then unnamed clusters (biggest first),
    # hidden people always at the end.
    items.sort(
        key=lambda p: (p["hidden"], p["name"] == "", p["name"].lower() or "", -p["face_count"])
    )
    return {
        "available": faces.available(),
        "reason": faces.unavailable_reason() or None,
        "persons": items,
    }


class DetectRequest(BaseModel):
    video_ids: list[int] | None = None
    force: bool = False


@router.post("/projects/{pid}/faces/detect")
def faces_detect(pid: str, body: DetectRequest) -> dict:
    video_dir = resolve_project(pid)
    if not faces.available():
        raise HTTPException(409, faces.unavailable_reason())
    with dbm.open_session(video_dir) as db:
        if body.video_ids:
            ids = body.video_ids
        else:
            ids = [v.id for v in db.scalars(select(Video).order_by(Video.filename))]
    queued = sum(
        1 for vid in ids if pipeline.queue_faces_job(pid, video_dir, vid, force=body.force)
    )
    return {"queued": queued}


@router.post("/projects/{pid}/people/recluster")
def people_recluster(pid: str) -> dict:
    video_dir = resolve_project(pid)
    return {"queued": pipeline.queue_recluster_job(pid, video_dir)}


class PersonEdit(BaseModel):
    name: str | None = None
    cover_face_id: int | None = None
    hidden: bool | None = None


@router.patch("/projects/{pid}/people/{person_id}")
def person_update(pid: str, person_id: int, body: PersonEdit) -> dict:
    """Rename a person, pick its cover face and/or hide it. Giving it a name
    another person already has (case-insensitive) merges this one into the
    existing person — naming two clusters the same is the natural way to say
    "these are the same person". Hidden people keep their faces (new
    detections still match them) but leave the main list, the Review chips
    and the AI context."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        person = db.get(Person, person_id)
        if person is None:
            raise HTTPException(404, "person not found")

        if body.hidden is not None:
            person.hidden = body.hidden

        if body.cover_face_id is not None:
            face = db.get(Face, body.cover_face_id)
            if face is None or face.person_id != person_id or face.ignored:
                raise HTTPException(400, "cover face must be one of this person's faces")
            person.cover_face_id = face.id

        if body.name is not None:
            name = body.name.strip()
            existing = None
            if name:
                existing = db.scalar(
                    select(Person).where(
                        Person.id != person_id, func.lower(Person.name) == name.lower()
                    )
                )
            if existing is not None:
                faces.merge_persons(db, person, existing)
                existing.name = name  # keep the freshly typed capitalization
                existing.hidden = False  # typing their name signals interest
                faces.fix_cover(db, existing)
                db.commit()
                result = _person_dict(db, existing)
                broadcaster.publish(pid, "people", {})
                return result
            person.name = name

        db.commit()
        result = _person_dict(db, person)
    broadcaster.publish(pid, "people", {})
    return result


class MergeRequest(BaseModel):
    into_id: int


@router.post("/projects/{pid}/people/{person_id}/merge")
def person_merge(pid: str, person_id: int, body: MergeRequest) -> dict:
    video_dir = resolve_project(pid)
    if person_id == body.into_id:
        raise HTTPException(400, "cannot merge a person into itself")
    with dbm.open_session(video_dir) as db:
        src = db.get(Person, person_id)
        dst = db.get(Person, body.into_id)
        if src is None or dst is None:
            raise HTTPException(404, "person not found")
        faces.merge_persons(db, src, dst)
        faces.fix_cover(db, dst)
        db.commit()
        result = _person_dict(db, dst)
    broadcaster.publish(pid, "people", {})
    return result


@router.delete("/projects/{pid}/people/{person_id}")
def person_delete(pid: str, person_id: int) -> dict:
    """Dissolve a person: its faces become unassigned (not ignored)."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        person = db.get(Person, person_id)
        if person is None:
            raise HTTPException(404, "person not found")
        for f in list(person.faces):
            f.person_id = None
            f.similarity = None
        db.delete(person)
        db.commit()
    broadcaster.publish(pid, "people", {})
    return {"ok": True}


@router.get("/projects/{pid}/people/{person_id}/faces")
def person_faces(pid: str, person_id: int) -> list[dict]:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        person = db.get(Person, person_id)
        if person is None:
            raise HTTPException(404, "person not found")
        rows = sorted(person.faces, key=lambda f: (f.video_id, f.t))
        return [_face_dict(f) for f in rows if not f.ignored]


@router.get("/projects/{pid}/videos/{vid}/faces")
def video_faces(pid: str, vid: int) -> list[dict]:
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        video = db.get(Video, vid)
        if video is None:
            raise HTTPException(404, "video not found")
        return [_face_dict(f) for f in sorted(video.faces, key=lambda f: f.t)]


class FaceEdit(BaseModel):
    person_id: int | None = None
    ignored: bool | None = None


@router.patch("/projects/{pid}/faces/{face_id}")
def face_update(pid: str, face_id: int, body: FaceEdit) -> dict:
    """Manual correction: move a face to another person, detach it
    (person_id: null) or mark it as not-a-person (ignored). Send person_id
    explicitly (even null) to change assignment; omit it to leave as is."""
    video_dir = resolve_project(pid)
    with dbm.open_session(video_dir) as db:
        face = db.get(Face, face_id)
        if face is None:
            raise HTTPException(404, "face not found")
        touched: set[int] = set()
        if "person_id" in body.model_fields_set:
            if body.person_id is not None and db.get(Person, body.person_id) is None:
                raise HTTPException(404, "target person not found")
            if face.person_id is not None:
                touched.add(face.person_id)
            face.person_id = body.person_id
            face.similarity = None
            if body.person_id is not None:
                touched.add(body.person_id)
        if body.ignored is not None:
            face.ignored = body.ignored
            if face.person_id is not None:
                touched.add(face.person_id)
        db.flush()
        for pid_ in touched:
            person = db.get(Person, pid_)
            if person is not None:
                db.expire(person, ["faces"])
                faces.recompute_centroid(db, person)
                faces.fix_cover(db, person)
        db.commit()
        result = _face_dict(face)
    broadcaster.publish(pid, "people", {})
    return result
