"""In-app timeline auto-composition through a one-shot LLM prompt.

The Montage page can ask the Antigravity CLI (agy) or an OpenAI-compatible
endpoint to compose the timeline: the whole project (videos + song structure
+ current timeline) is serialized into one prompt, the model replies with a
JSON list of actions, and the actions are applied through timeline_ops (the
same validation the REST API and the MCP server use). Claude via MCP remains
a separate, external path (backend/mcp_server.py) and is not handled here.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import db as dbm
from .. import settings
from ..models import Face, Person, Song, Video
from . import gemini, jobs, lyrics as lyrics_svc, openai_client
from . import timeline_ops as ops
from .ai import AIError, _extract_json

log = logging.getLogger(__name__)

MAX_ACTIONS = 300
MAX_BEATS_IN_PROMPT = 500
MAX_LYRIC_LINES_IN_PROMPT = 200

COMPOSE_PROMPT = """\
You are composing a video montage timeline synced to a song. Below is the
full project state as JSON: the song (sections, BPM, beat timestamps), the
candidate videos (with AI descriptions, hashtags, mood/energy/scene data,
user star ratings 0-5, AI scores 1-10, and hand-picked interesting ranges),
and the current timeline (it may already contain clips, which you may keep,
move or remove).

PROJECT:
{context}

USER INSTRUCTIONS:
{instructions}

Reply with ONLY a JSON object (no markdown fence, no prose):
{{
  "summary": "one or two sentences describing the montage you composed",
  "actions": [
    {{"action": "clear_track", "track": 0}},
    {{"action": "remove", "clip_id": 12}},
    {{"action": "move", "clip_id": 13, "timeline_start": 10.0, "track": 1, "source_in": 2.0, "source_out": 5.0}},
    {{"action": "place", "video_id": 3, "track": 0, "timeline_start": 0.0, "source_in": 1.0, "source_out": 4.5}}
  ]
}}
Rules:
- Actions are applied in order. "track" is a 0-based track index.
- In "move", all fields except clip_id are optional (only provided ones change).
- Cut on beats: clip boundaries should land on beat timestamps (downbeats are
  the strongest cut points). Prefer section boundaries for scene changes.
- Clips on the same track must not overlap; source_in/source_out must stay
  within the video's duration; the montage should not run past the song's end.
- Prefer high-star and high-score videos and their hand-picked ranges; vary
  the footage instead of reusing one video back to back.
- If the song includes lyrics/vocal data (timestamped lines, per-section
  vocal_ratio, instrumental_ranges): match footage to what the lyrics say or
  evoke, use calmer/scenic shots over melody-only instrumental passages, and
  save the most striking footage for the chorus.
- Videos may list "people": the named people appearing in them. Honor
  instructions that reference people (e.g. "more shots of Ana", "only clips
  with Marc"), and when no instruction says otherwise, vary who is on screen
  across the montage.
- Videos may carry "shot_at" (recording timestamp), "camera" and "lens". Use
  these for continuity: clips shot close in time or on the same camera likely
  belong to the same moment/scene, so keep them together and roughly ordered by
  shot_at unless an instruction says otherwise.
- Videos may carry AI-analyzed "energy" (low/medium/high motion), "mood"
  (emotional tone words), "scene", "time_of_day" and "shot_type".
- Match energy to the music: put high-energy clips on the chorus/drop and other
  intense sections, low-energy scenic clips on intros, outros and instrumental
  passages. Match mood to the feel of each section.
- Vary scene and shot_type between consecutive clips (e.g. avoid three drone
  shots in a row), and group time_of_day into coherent progressions (day →
  sunset → night) rather than ping-ponging, unless asked otherwise.\
"""


class ComposeError(RuntimeError):
    pass


def provider() -> str:
    return settings.get().composer.provider


def available() -> bool:
    active = provider()
    if active == "agy":
        return gemini.agy_available()
    if active == "openai":
        return openai_client.configured()
    return False  # mcp: composition happens externally in Claude


def unavailable_reason() -> str:
    active = provider()
    if active == "mcp":
        return (
            "Composer provider is Claude via MCP — compose from Claude as before, "
            "or pick agy/OpenAI in Settings to compose from here."
        )
    if active == "agy":
        return "Antigravity CLI (agy) not found. Install it or change the composer provider."
    return (
        "OpenAI-compatible endpoint not configured (base URL + model needed) "
        "for the composer. Fill them in Settings."
    )


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def build_context(db: Session) -> dict:
    """Everything the model needs, mirroring what Claude sees over MCP
    (project summary, videos, sections, beats, timeline)."""
    song = db.scalar(select(Song))
    song_ctx = None
    if song is not None:
        beats = song.beats
        lyr = song.lyrics if song.lyrics is not None and song.lyrics.status == "ready" else None
        vocals = lyrics_svc.vocal_ranges(lyr.segments) if lyr else None
        song_ctx = {
            "duration": _round(song.duration),
            "bpm": _round(song.bpm),
            "sections": [
                {
                    "start": _round(s.start),
                    "end": _round(s.end),
                    "label": s.label,
                    "energy": _round(s.energy),
                    **(
                        {"vocal_ratio": lyrics_svc.vocal_ratio(s.start, s.end, vocals)}
                        if vocals is not None
                        else {}
                    ),
                }
                for s in song.sections
            ],
            "downbeats": [_round(b) for b in song.downbeats],
        }
        if lyr:
            song_ctx["lyrics_language"] = lyr.language
            song_ctx["lyrics"] = [
                {"start": _round(s["start"]), "end": _round(s["end"]), "text": s["text"]}
                for s in lyr.segments[:MAX_LYRIC_LINES_IN_PROMPT]
            ]
            song_ctx["instrumental_ranges"] = lyrics_svc.instrumental_ranges(
                vocals, song.duration, settings.get().lyrics.min_instrumental_gap
            )
        if len(beats) <= MAX_BEATS_IN_PROMPT:
            song_ctx["beats"] = [_round(b) for b in beats]
        else:
            song_ctx["beats_note"] = (
                f"{len(beats)} beats omitted for brevity; cut on the downbeats "
                "above or interpolate from the BPM"
            )
    # Named people per video (from face detection), one batch query.
    people_by_video: dict[int, set[str]] = {}
    for vid, name in db.execute(
        select(Face.video_id, Person.name)
        .join(Person, Face.person_id == Person.id)
        .where(Face.ignored.is_(False), Person.name != "", Person.hidden.is_(False))
    ):
        people_by_video.setdefault(vid, set()).add(name)
    aspects = settings.get().analysis
    videos = []
    for v in db.scalars(select(Video).order_by(Video.filename)):
        if v.rating and v.rating.rejected:
            continue
        entry = {
            "id": v.id,
            "filename": v.filename,
            "duration": _round(v.duration),
            "stars": v.rating.stars if v.rating else 0,
            "ai_score": v.analysis.ai_score if v.analysis else None,
            "description": v.analysis.description if v.analysis else "",
            "hashtags": v.analysis.hashtags if v.analysis else [],
            **(
                {"people": sorted(people_by_video[v.id])}
                if v.id in people_by_video
                else {}
            ),
            "ranges": [
                {"t_in": _round(r.t_in), "t_out": _round(r.t_out), "label": r.label}
                for r in v.ranges
            ],
        }
        # Optional analysis aspects: only when enabled in Settings AND present
        # (keeps the prompt compact for old/partial analyses).
        if (a := v.analysis) is not None:
            if aspects.mood and a.mood:
                entry["mood"] = a.mood
            if aspects.energy and a.energy:
                entry["energy"] = a.energy
            if aspects.scene:
                if a.scene:
                    entry["scene"] = a.scene
                if a.time_of_day:
                    entry["time_of_day"] = a.time_of_day
                if a.shot_type:
                    entry["shot_type"] = a.shot_type
        # Technical/EXIF context so the composer can group by shooting time or
        # camera (e.g. keep angles from the same camera together). Compact: the
        # curated fields only, no raw tag dump.
        meta = v.meta
        cam = " ".join(x for x in (meta.get("make"), meta.get("model")) if x)
        if v.shot_at:
            entry["shot_at"] = v.shot_at
        if cam:
            entry["camera"] = cam
        if meta.get("lens"):
            entry["lens"] = meta["lens"]
        videos.append(entry)
    timeline = ops.timeline_state(db)
    for track in timeline["tracks"]:
        for clip in track["clips"]:
            for key in ("timeline_start", "source_in", "source_out", "duration"):
                clip[key] = _round(clip[key])
    return {"song": song_ctx, "videos": videos, "timeline": timeline}


def build_prompt(context: dict, instructions: str) -> str:
    return COMPOSE_PROMPT.format(
        context=json.dumps(context, separators=(",", ":")),
        instructions=instructions.strip() or "(none — compose a good montage for the whole song)",
    )


def parse_actions(raw: str) -> tuple[list[dict], str]:
    """Validate the model's reply into (actions, summary)."""
    data = json.loads(_extract_json(raw))
    if not isinstance(data, dict):
        raise ComposeError("model reply is not a JSON object")
    actions = data.get("actions")
    if not isinstance(actions, list):
        raise ComposeError('model reply has no "actions" list')
    if len(actions) > MAX_ACTIONS:
        raise ComposeError(f"too many actions ({len(actions)} > {MAX_ACTIONS})")
    known = {"place", "move", "remove", "clear_track"}
    for i, action in enumerate(actions):
        if not isinstance(action, dict) or action.get("action") not in known:
            raise ComposeError(f"action #{i} is invalid: {json.dumps(action)[:120]}")
    return actions, str(data.get("summary", "")).strip()


def apply_actions(db: Session, actions: list[dict], placed_by: str) -> tuple[int, list[str]]:
    """Apply actions in order; failed ones are collected, not fatal."""
    applied = 0
    errors: list[str] = []
    for i, a in enumerate(actions):
        kind = a["action"]
        try:
            if kind == "place":
                ops.place_clip(
                    db,
                    video_id=int(a["video_id"]),
                    track_ref=int(a["track"]),
                    timeline_start=float(a["timeline_start"]),
                    source_in=float(a["source_in"]),
                    source_out=float(a["source_out"]),
                    placed_by=placed_by,
                    track_by_index=True,
                    speed=float(a.get("speed", 1.0)),
                )
            elif kind == "move":
                ops.update_clip(
                    db,
                    clip_id=int(a["clip_id"]),
                    timeline_start=None if a.get("timeline_start") is None else float(a["timeline_start"]),
                    track_ref=None if a.get("track") is None else int(a["track"]),
                    source_in=None if a.get("source_in") is None else float(a["source_in"]),
                    source_out=None if a.get("source_out") is None else float(a["source_out"]),
                    track_by_index=True,
                    speed=None if a.get("speed") is None else float(a["speed"]),
                )
            elif kind == "remove":
                ops.remove_clip(db, int(a["clip_id"]))
            else:  # clear_track
                # clear_track iterates the Track.clips relationship, which can
                # be stale after earlier mutations in this same session (the
                # REST API and MCP server never hit this: one session per op).
                db.expire_all()
                ops.clear_track(db, int(a["track"]), track_by_index=True)
            applied += 1
        except (ops.TimelineError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"action #{i} ({kind}): {exc}")
    db.expire_all()  # so same-session reads (timeline_state) see the result
    return applied, errors


def _ask(prompt: str) -> str:
    active = provider()
    if active == "agy":
        return gemini.run_prompt(prompt)
    if active == "openai":
        return openai_client.chat(prompt)
    raise ComposeError(unavailable_reason())


def run_compose(pid: str, video_dir: Path, instructions: str, job: jobs.Job) -> dict:
    """Build the prompt, ask the provider, apply the returned actions.
    Runs inside a background job; returns the summary dict for the UI."""
    active = provider()
    if not available():
        raise ComposeError(unavailable_reason())

    with dbm.open_session(video_dir) as db:
        context = build_context(db)
        db.commit()
    if not context["videos"]:
        raise ComposeError("no candidate videos to compose with")
    prompt = build_prompt(context, instructions)
    log.info("compose: provider=%s, %d video(s)", active, len(context["videos"]))
    log.debug("compose prompt:\n%s", prompt)

    actions: list[dict] = []
    summary = ""
    last_error: Exception | None = None
    for attempt in range(1, 3):
        jobs.update(job, 0.2, f"asking {active} (attempt {attempt}/2)")
        raw = _ask(prompt)
        log.debug("compose raw response:\n%s", raw)
        try:
            actions, summary = parse_actions(raw)
            break
        except (ValueError, AIError, ComposeError) as exc:
            last_error = exc
            log.warning(
                "attempt %d/2: could not parse compose response (%s)\n--- raw ---\n%s",
                attempt,
                exc,
                raw.strip()[:1000],
            )
    else:
        raise ComposeError(f"could not parse compose response: {last_error}")

    jobs.update(job, 0.8, f"applying {len(actions)} action(s)")
    with dbm.open_session(video_dir) as db:
        applied, errors = apply_actions(db, actions, placed_by=active)
        db.commit()
    if errors:
        log.warning("compose: %d/%d action(s) rejected:\n%s", len(errors), len(actions), "\n".join(errors))
    return {
        "provider": active,
        "applied": applied,
        "errors": errors,
        "summary": summary,
        "actions_total": len(actions),
    }
