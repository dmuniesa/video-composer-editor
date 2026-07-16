"""Antigravity CLI (agy) invocation.

Gemini is reached by shelling out to Google's Antigravity CLI in
non-interactive mode (`-p`/`--print`). The command template comes from
Settings (AGY_CMD env overrides it,
which tests use to substitute a fake). Files are pulled into context with the
CLI's @path syntax inside the prompt; prompts live in services/ai.py and
services/lyrics.py. @ refs work for images and MP4 containers, but raw audio
files (mp3/wav) are refused by MIME type — remux audio to .mp4 first.

@path references must be ABSOLUTE: agy does not honor the subprocess cwd — it
executes in a global scratch dir (~/.gemini/antigravity-cli/scratch) shared by
every invocation, where relative refs hit stale copies from earlier runs."""
from __future__ import annotations

import logging
import os
import shlex
import subprocess
import time
from pathlib import Path
from shutil import which

from .. import settings

log = logging.getLogger(__name__)


class AgyError(RuntimeError):
    pass


def agy_command() -> list[str]:
    cmd = (
        os.environ.get("AGY_CMD")
        or settings.get().ai.agy_cmd
        or "agy --dangerously-skip-permissions -p"
    )
    return shlex.split(cmd)


def agy_available() -> bool:
    try:
        return which(agy_command()[0]) is not None
    except (ValueError, IndexError):
        return False


def run_prompt(prompt: str, cwd: Path | None = None) -> str:
    template = agy_command()
    cmd = [*template, prompt]
    timeout = settings.get().ai.timeout_s
    log.info(
        "agy call: %s (prompt %d chars, cwd=%s, timeout=%ss)",
        shlex.join(template),
        len(prompt),
        cwd,
        timeout,
    )
    log.debug("agy prompt:\n%s", prompt)
    started = time.monotonic()
    try:
        out = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            # agy emits UTF-8 regardless of the console codepage; without this,
            # Windows decodes with cp1252 and any accented character kills the
            # reader thread, leaving stdout=None.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
        )
    except FileNotFoundError as exc:
        raise AgyError(
            f"Antigravity CLI not found ({template[0]!r}). Install it and "
            "log in once (`agy`), or fix the command in Settings."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        log.error("agy timed out after %ss", timeout)
        raise AgyError(f"agy timed out after {timeout}s") from exc
    elapsed = time.monotonic() - started
    if out.returncode != 0:
        log.error(
            "agy exited %d in %.1fs\n--- stderr ---\n%s\n--- stdout ---\n%s",
            out.returncode,
            elapsed,
            out.stderr.strip(),
            out.stdout.strip(),
        )
        raise AgyError(f"agy exited {out.returncode}: {(out.stderr or out.stdout).strip()[:400]}")
    if not out.stdout.strip() and out.stderr.strip():
        # agy 1.1.2 exits 0 with empty stdout when its agent's tool calls are
        # auto-denied in headless mode (e.g. read_file without
        # --dangerously-skip-permissions); the reason only appears on stderr.
        log.error("agy produced no output in %.1fs\n--- stderr ---\n%s", elapsed, out.stderr.strip())
        raise AgyError(f"agy produced no output: {out.stderr.strip()[:400]}")
    log.info("agy ok in %.1fs (%d chars out)", elapsed, len(out.stdout))
    log.debug("agy raw output:\n%s", out.stdout)
    return out.stdout
