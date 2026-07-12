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

Analyze the clip and reply with ONLY a JSON object (no markdown fence, no prose):
{{
  "description": "one or two sentences describing what happens in the clip",
  "score": <integer 1-10, how visually appealing/usable this clip is for a montage>,
  "hashtags": ["lowercase", "keywords", "like", "beach", "sunset", "people", "drone", "food"],
  "highlights": [{{"frame": <0-based index of a standout frame>, "reason": "why"}}]
}}
Rules: 3 to 8 hashtags, single words, lowercase, no # symbol. Judge stability,
light, composition and subject interest for the score.\
"""

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


def _ask(prompt: str, images: list[Path], workdir: Path | None) -> str:
    active = provider()
    if active == "agy":
        return gemini.run_prompt(prompt, cwd=workdir)
    if active == "openai":
        return openai_client.chat(prompt, images=images)
    raise AIError(unavailable_reason())


def analyze_video_frames(frame_paths: list[Path], workdir: Path) -> dict:
    """Describe/score/hashtag a clip from its sampled frames.

    Returns {"description", "score", "hashtags", "highlights", "raw"}.
    Retries once on unparseable output."""
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
    prompt = VIDEO_PROMPT.format(frames_intro=intro)

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
            return {
                "description": str(data.get("description", "")).strip(),
                "score": max(1, min(10, int(data.get("score", 5)))),
                "hashtags": [h for h in hashtags if h][:8],
                "highlights": data.get("highlights", []),
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
