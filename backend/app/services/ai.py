"""AI provider dispatch: analyzes video frames and labels song sections with
either the Antigravity CLI (Gemini) or any OpenAI-compatible endpoint
(z.ai GLM, OpenAI, Ollama...), per the user settings.

Shared here: the prompts, robust JSON extraction from chatty model output,
and normalization of the results."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .. import settings
from . import gemini, openai_client

log = logging.getLogger(__name__)


class AIError(RuntimeError):
    pass


VIDEO_PROMPT = """\
You are helping select vacation video clips for a music montage.
{frames_intro}
{people_note}
Analyze the clip and reply with ONLY a JSON object (no markdown fence, no prose):
{{
{fields}
}}
Rules:
{rules}\
"""

_BASE_FIELDS = [
    '"description": "one or two sentences describing what happens in the clip"',
    '"score": <integer 1-10, how visually appealing/usable this clip is for a montage>',
    '"hashtags": ["lowercase", "keywords", "like", "beach", "sunset", "people", "drone", "food"]',
]
_BASE_RULES = [
    "3 to 8 hashtags, single words, lowercase, no # symbol.",
    "Judge stability, light, composition and subject interest for the score.",
]

# Optional analysis aspects, each toggleable in Settings (AnalysisSettings).
# Keys match the AnalysisSettings field names; a disabled aspect is neither
# requested in the prompt nor read from the response.
_ASPECT_FIELDS: dict[str, list[str]] = {
    "mood": ['"mood": ["one", "to", "three"]'],
    "energy": ['"energy": "low" | "medium" | "high"'],
    "scene": [
        '"scene": "beach"',
        '"time_of_day": "day" | "sunrise" | "sunset" | "night"',
        '"shot_type": "drone"',
    ],
}
_ASPECT_RULES: dict[str, list[str]] = {
    "mood": [
        '"mood": 1-3 lowercase words for the emotional tone (e.g. happy, calm, '
        "epic, funny, romantic, peaceful, tense, nostalgic)."
    ],
    "energy": [
        '"energy": how much motion/action is visible (subjects and camera), not '
        "how good the clip is. Static scenery = low; walking/talking = medium; "
        "sports, jumping, fast camera moves = high."
    ],
    "scene": [
        '"scene": one short lowercase label for the setting (beach, city, '
        "mountain, forest, pool, indoor, restaurant, road, boat, snow...).",
        '"shot_type": the dominant framing: drone, wide, medium, close-up, '
        "selfie, pov, underwater or timelapse.",
    ],
}

PEOPLE_NOTE = (
    "\nFace recognition already identified these people in this clip: {names}. "
    "Refer to them by name in the description when you can tell who does what "
    '(e.g. "Maria diving off the boat"). Do not invent names for anyone else.\n'
)

SECTION_PROMPT = """\
You are labeling the structure of a song for a video montage editor.
The song is {duration:.1f}s long at {bpm:.1f} BPM. An audio analysis produced
these unlabeled sections (start-end seconds, relative RMS energy 0-1, and a
cluster id where sections sharing a cluster sound similar):

{table}

Reply with ONLY a JSON array (no markdown fence), one item per section, in order:
[{{"index": 0, "label": "intro"}}, ...]
Use labels from: intro, verse, pre-chorus, chorus, bridge, instrumental, drop, outro.
Sections sharing a cluster id usually share a label (e.g. all choruses).
High-energy repeated sections are usually the chorus/drop.{lyrics_note}\
"""

LYRICS_NOTE = """
Some sections include vocals=<percent of the section with singing> and a lyrics
snippet. Sections with (near) zero vocals are instrumental/intro/outro; sections
repeating the same lyrics are the chorus; unique lyrics suggest verses."""


def provider() -> str | None:
    """Resolve the effective provider, or None when AI is unavailable."""
    ai = settings.get().ai
    if ai.provider == "off":
        return None
    if ai.provider == "agy":
        return "agy" if gemini.agy_available() else None
    if ai.provider == "openai":
        return "openai" if openai_client.configured() else None
    # auto
    if gemini.agy_available():
        return "agy"
    if openai_client.configured():
        return "openai"
    return None


def available() -> bool:
    return provider() is not None


def unavailable_reason() -> str:
    ai = settings.get().ai
    if ai.provider == "off":
        return "AI analysis is disabled in Settings."
    return (
        "No AI provider available. Install the Antigravity CLI (agy) and sign in, "
        "or configure an OpenAI-compatible endpoint (base URL + model) in Settings."
    )


def _extract_json(text: str) -> str:
    """Pull the first JSON object/array out of possibly chatty model output."""
    fenced = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start_positions = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not start_positions:
        raise AIError(f"no JSON in model output: {text.strip()[:200]}")
    start = min(start_positions)
    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    raise AIError(f"unterminated JSON in model output: {text.strip()[:200]}")


# Normalization maps/helpers for the optional aspects. None of these raise:
# missing keys, wrong types or unexpected vocabulary degrade to None/[] so a
# partial response never triggers the parse-retry.
_ENERGY = {
    "low": "low", "medium": "medium", "med": "medium", "high": "high",
    "1": "low", "2": "low", "3": "medium", "4": "high", "5": "high",
}
_TIME_OF_DAY = {
    "day": "day", "daytime": "day", "morning": "day", "afternoon": "day", "noon": "day",
    "sunrise": "sunrise", "dawn": "sunrise",
    "sunset": "sunset", "dusk": "sunset", "golden hour": "sunset", "goldenhour": "sunset",
    "night": "night", "evening": "night",
}
_SHOT_ALIASES = {
    "aerial": "drone", "closeup": "close-up", "close up": "close-up",
    "extreme close-up": "close-up", "point of view": "pov", "time-lapse": "timelapse",
}


def _word_list(value, cap: int) -> list[str]:
    """Tag-like field: accept a list or a single string, lowercase, strip to
    [a-z0-9], drop empties, cap the count (same rules as hashtags)."""
    if isinstance(value, str):
        value = re.split(r"[\s,/]+", value)
    if not isinstance(value, list):
        return []
    words = (re.sub(r"[^a-z0-9]", "", str(w).lower().lstrip("#")) for w in value)
    return [w for w in words if w][:cap]


def _enum_or_none(value, mapping: dict[str, str]) -> str | None:
    return mapping.get(str(value or "").strip().lower())


def _label_or_none(value, max_len: int = 24) -> str | None:
    """Free-ish short label (scene/shot_type): lowercase, keep letters, digits,
    hyphens and spaces; None when empty."""
    text = re.sub(r"[^a-z0-9 \-]", "", str(value or "").strip().lower()).strip()
    return text[:max_len] or None


def _ask(prompt: str, images: list[Path], workdir: Path | None) -> str:
    active = provider()
    if active == "agy":
        return gemini.run_prompt(prompt, cwd=workdir)
    if active == "openai":
        return openai_client.chat(prompt, images=images)
    raise AIError(unavailable_reason())


def analyze_video_frames(
    frame_paths: list[Path], workdir: Path, people: list[str] | None = None
) -> dict:
    """Describe/score/hashtag a clip from its sampled frames, plus whichever
    optional aspects are enabled in Settings (mood, energy, scene/time_of_day/
    shot_type). `people` are names already identified in the clip by face
    recognition; when given (and the toggle is on) the description can use them.

    Returns {"description", "score", "hashtags", "mood", "energy", "scene",
    "time_of_day", "shot_type", "raw"} — every key always present;
    disabled/missing aspects come back as None/[].
    Retries once on unparseable output."""
    aspects = settings.get().analysis
    active = provider()
    if active == "agy":
        # Absolute paths are required: agy ignores the process cwd and runs in
        # a global shared scratch dir (~/.gemini/antigravity-cli/scratch), so
        # relative @frame_00.jpg refs resolve to whatever stale frames a
        # previous analysis left there, mixing descriptions between videos.
        refs = " ".join(f"@{p.resolve()}" for p in frame_paths)
        intro = f"These images are frames sampled evenly from ONE video clip, in order: {refs}"
    else:
        intro = "The attached images are frames sampled evenly from ONE video clip, in order."
    people_note = ""
    if people and aspects.people_in_prompt:
        people_note = PEOPLE_NOTE.format(names=", ".join(people))
    enabled = [k for k in _ASPECT_FIELDS if getattr(aspects, k)]
    fields = _BASE_FIELDS + [f for k in enabled for f in _ASPECT_FIELDS[k]]
    rules = _BASE_RULES + [r for k in enabled for r in _ASPECT_RULES[k]]
    prompt = VIDEO_PROMPT.format(
        frames_intro=intro,
        people_note=people_note,
        fields=",\n".join(f"  {f}" for f in fields),
        rules="\n".join(f"- {r}" for r in rules),
    )

    log.info(
        "analyze video: provider=%s, %d frame(s) in %s", active, len(frame_paths), workdir
    )
    last_error: Exception | None = None
    for attempt in range(1, 3):
        raw = _ask(prompt, frame_paths, workdir)
        try:
            data = json.loads(_extract_json(raw))
            hashtags = [
                re.sub(r"[^a-z0-9]", "", str(h).lower().lstrip("#"))
                for h in data.get("hashtags", [])
            ]
            shot_type = None
            if aspects.scene:
                shot_type = _enum_or_none(data.get("shot_type"), _SHOT_ALIASES) or _label_or_none(
                    data.get("shot_type"), 16
                )
            return {
                "description": str(data.get("description", "")).strip(),
                "score": max(1, min(10, int(data.get("score", 5)))),
                "hashtags": [h for h in hashtags if h][:8],
                "mood": _word_list(data.get("mood"), cap=3) if aspects.mood else [],
                "energy": _enum_or_none(data.get("energy"), _ENERGY) if aspects.energy else None,
                "scene": _label_or_none(data.get("scene")) if aspects.scene else None,
                "time_of_day": (
                    _enum_or_none(data.get("time_of_day"), _TIME_OF_DAY) if aspects.scene else None
                ),
                "shot_type": shot_type,
                "raw": raw,
            }
        except (ValueError, TypeError, AIError) as exc:
            last_error = exc
            log.warning(
                "attempt %d/2: could not parse AI response (%s)\n--- raw ---\n%s",
                attempt,
                exc,
                raw.strip()[:1000],
            )
    raise AIError(f"could not parse AI response: {last_error}")


def label_sections(duration: float, bpm: float, sections: list[dict]) -> list[str]:
    """Semantically label sections found by librosa. Returns one label per
    section (same order); callers degrade gracefully on failure.

    Sections may carry optional lyric hints from the Whisper transcription:
    "vocal_ratio" (0-1) and "lyrics" (snippet of the sung lines)."""
    has_lyrics = any("vocal_ratio" in s for s in sections)

    def row(i: int, s: dict) -> str:
        line = f"{i}: {s['start']:.1f}-{s['end']:.1f}s energy={s['energy']:.2f} cluster={s.get('cluster', 0)}"
        if "vocal_ratio" in s:
            line += f" vocals={round(s['vocal_ratio'] * 100)}%"
            if s.get("lyrics"):
                line += f' lyrics="{s["lyrics"]}"'
        return line

    table = "\n".join(row(i, s) for i, s in enumerate(sections))
    prompt = SECTION_PROMPT.format(
        duration=duration,
        bpm=bpm or 0.0,
        table=table,
        lyrics_note=LYRICS_NOTE if has_lyrics else "",
    )
    raw = _ask(prompt, [], None)
    data = json.loads(_extract_json(raw))
    labels = [""] * len(sections)
    for item in data:
        idx = int(item.get("index", -1))
        if 0 <= idx < len(labels):
            labels[idx] = str(item.get("label", "")).strip().lower()
    return labels


def test_connection() -> dict:
    """Settings-page probe: sends a trivial prompt through the active provider."""
    active = provider()
    if active is None:
        return {"ok": False, "provider": None, "error": unavailable_reason()}
    try:
        raw = _ask('Reply with ONLY this JSON: {"pong": true}', [], None)
        _extract_json(raw)
        return {"ok": True, "provider": active}
    except Exception as exc:  # noqa: BLE001 - report anything to the UI
        return {"ok": False, "provider": active, "error": str(exc)}
