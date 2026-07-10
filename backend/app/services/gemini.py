"""Antigravity CLI (agy) wrapper.

Gemini is reached by shelling out to Google's Antigravity CLI in headless
mode. The exact binary/flags are configurable through AGY_CMD because the
CLI is young and its flags may change (and tests substitute a fake).

Default invocation:  agy --headless -p "<prompt>"
Files are pulled into context with the CLI's @path syntax inside the prompt
(images are officially supported by the Antigravity agent).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

DEFAULT_AGY_CMD = "agy --headless -p"

VIDEO_PROMPT = """\
You are helping select vacation video clips for a music montage.
These images are frames sampled evenly from ONE video clip, in order: {frame_refs}

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
High-energy repeated sections are usually the chorus/drop.\
"""


class AgyError(RuntimeError):
    pass


def agy_command() -> list[str]:
    return shlex.split(os.environ.get("AGY_CMD", DEFAULT_AGY_CMD))


def agy_available() -> bool:
    from shutil import which

    return which(agy_command()[0]) is not None


def _run(prompt: str, cwd: Path | None = None, timeout: int = 300) -> str:
    cmd = [*agy_command(), prompt]
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
    except FileNotFoundError as exc:
        raise AgyError(
            f"Antigravity CLI not found ({agy_command()[0]!r}). Install it and "
            "log in once (`agy`), or point AGY_CMD at it."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AgyError(f"agy timed out after {timeout}s") from exc
    if out.returncode != 0:
        raise AgyError(f"agy exited {out.returncode}: {(out.stderr or out.stdout).strip()[:400]}")
    return out.stdout


def _extract_json(text: str) -> str:
    """Pull the first JSON object/array out of possibly chatty CLI output."""
    fenced = re.search(r"```(?:json)?\s*([\[{].*?[\]}])\s*```", text, re.DOTALL)
    if fenced:
        return fenced.group(1)
    start_positions = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not start_positions:
        raise AgyError(f"no JSON in agy output: {text.strip()[:200]}")
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
    raise AgyError(f"unterminated JSON in agy output: {text.strip()[:200]}")


def analyze_video_frames(frame_paths: list[Path], workdir: Path) -> dict:
    """Ask Gemini to describe/score/hashtag a clip from its sampled frames.

    Returns {"description", "score", "hashtags", "highlights", "raw"}.
    Retries once on unparseable output.
    """
    refs = " ".join(f"@{p.relative_to(workdir)}" for p in frame_paths)
    prompt = VIDEO_PROMPT.format(frame_refs=refs)

    last_error: Exception | None = None
    for _ in range(2):
        raw = _run(prompt, cwd=workdir)
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
        except (ValueError, TypeError, AgyError) as exc:
            last_error = exc
    raise AgyError(f"could not parse agy response: {last_error}")


def label_sections(duration: float, bpm: float, sections: list[dict]) -> list[str]:
    """Ask Gemini to semantically label section boundaries found by librosa.

    `sections` items need: start, end, energy, cluster. Returns one label per
    section (same order). Raises AgyError on failure — callers degrade
    gracefully by keeping unlabeled sections.
    """
    table = "\n".join(
        f"{i}: {s['start']:.1f}-{s['end']:.1f}s energy={s['energy']:.2f} cluster={s['cluster']}"
        for i, s in enumerate(sections)
    )
    raw = _run(SECTION_PROMPT.format(duration=duration, bpm=bpm or 0.0, table=table))
    data = json.loads(_extract_json(raw))
    labels = [""] * len(sections)
    for item in data:
        idx = int(item.get("index", -1))
        if 0 <= idx < len(labels):
            labels[idx] = str(item.get("label", "")).strip().lower()
    return labels
