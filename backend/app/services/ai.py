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


# Longest clip attached as video to the analysis (agy video mode); longer
# clips fall back to sampled frames to keep uploads/latency bounded.
VIDEO_ATTACH_MAX_S = 180


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
    '"score": Rate how usable this clip is for a family music montage on a scale of 1-10 based on this strict rubric:\n'
    '    * 1-3: Unusable (extremely shaky, blurry, completely dark, or subject is blocked).\n'
    '    * 4-6: Mediocre/Filler (okay composition, normal walking/talking, slightly unstable).\n'
    '    * 7-8: Great (stable camera, good lighting, clear action, beautiful scenery, or clear faces).\n'
    '    * 9-10: Perfect (cinematic, strong positive emotions/smiles from the identified people, perfect composition).\n'
    '    * CRITICAL PENALTY: If the total clip duration is less than 3.0 seconds, the maximum score allowed is 4, regardless of how good it looks.\n'
    '    * USABILITY PENALTY: To score above a 6, the clip MUST have at least one stable, usable continuous segment (highlight) that lasts 1 second or more.',
]

# Optional analysis aspects, each toggleable in Settings (AnalysisSettings).
# Keys match the AnalysisSettings field names; a disabled aspect is neither
# requested in the prompt nor read from the response.
_ASPECT_FIELDS: dict[str, list[str]] = {
    "mood": ['"mood": ["one", "to", "three"]'],
    "energy": ['"energy": "low" | "medium" | "high"'],
    "scene": [
        '"scene": "beach"',
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


def _norm_highlight_ranges(value, duration: float) -> list[dict]:
    """[{"t_in", "t_out", "reason"}] from the model's {start_s, end_s, reason}
    items: floats clamped to [0, duration], at least 0.5s long, sorted, max 3.
    Invalid items are dropped; never raises."""
    if not isinstance(value, list) or duration <= 0:
        return []
    out = []
    for item in value:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start_s"))
            end = float(item.get("end_s"))
        except (TypeError, ValueError):
            continue
        start = max(0.0, min(start, duration))
        end = max(0.0, min(end, duration))
        if end - start < 0.5:
            continue
        out.append(
            {
                "t_in": round(start, 2),
                "t_out": round(end, 2),
                "reason": str(item.get("reason", "")).strip()[:200],
            }
        )
    out.sort(key=lambda h: h["t_in"])
    return out[:3]


def _ask(prompt: str, images: list[Path], workdir: Path | None) -> str:
    active = provider()
    if active == "agy":
        return gemini.run_prompt(prompt, cwd=workdir)
    if active == "openai":
        return openai_client.chat(prompt, images=images)
    raise AIError(unavailable_reason())


def analyze_clip(
    frame_paths: list[Path],
    workdir: Path,
    people: list[str] | None = None,
    video_file: Path | None = None,
    duration: float = 0.0,
) -> dict:
    """Describe/score/hashtag a clip, plus whichever optional aspects are
    enabled in Settings (mood, energy, scene/shot_type, highlights).

    The clip reaches the model either as `video_file` (the low-res preview.mp4,
    agy only — the caller decides per the agy_media setting; the model sees
    motion and can return highlight time ranges) or as the sampled
    `frame_paths`. `people` are names already identified by face recognition;
    when given (and the toggle is on) the description can use them.

    Returns {"description", "score", "hashtags", "mood", "energy", "scene",
    "shot_type", "highlights", "raw"} — every key always present;
    disabled/missing aspects come back as None/[]. Highlights are only
    requested in video mode. Retries once on unparseable output."""
    aspects = settings.get().analysis
    active = provider()
    if video_file is not None:
        # Absolute path required for the same reason as the frame refs below.
        intro = (
            f"The attached file is ONE video clip, {duration:.1f} seconds long: "
            f"@{video_file.resolve()}"
        )
    elif active == "agy":
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
    # Highlights need real timestamps, which only the video attachment gives —
    # from sampled stills the model cannot judge times, so don't ask.
    want_highlights = aspects.highlights and video_file is not None
    if want_highlights:
        fields.append('"highlights": [{"start_s": <seconds>, "end_s": <seconds>, "reason": "why"}]')
        rules.append(
            '"highlights": the 1-3 single best moments as time ranges in seconds '
            f"from the clip's start (between 0 and {duration:.1f}), about 0.5s "
            "precision, each at least 1s long. [] if nothing stands out."
        )
    prompt = VIDEO_PROMPT.format(
        frames_intro=intro,
        people_note=people_note,
        fields=",\n".join(f"  {f}" for f in fields),
        rules="\n".join(f"- {r}" for r in rules),
    )

    log.info(
        "analyze clip: provider=%s, %s in %s",
        active,
        "video attach" if video_file is not None else f"{len(frame_paths)} frame(s)",
        workdir,
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
                "shot_type": shot_type,
                "highlights": (
                    _norm_highlight_ranges(data.get("highlights"), duration)
                    if want_highlights
                    else []
                ),
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
