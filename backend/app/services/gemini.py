"""Antigravity CLI (agy) invocation.

Gemini is reached by shelling out to Google's Antigravity CLI in headless
mode. The command template comes from Settings (AGY_CMD env overrides it,
which tests use to substitute a fake). Files are pulled into context with the
CLI's @path syntax inside the prompt; prompts live in services/ai.py."""
from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from shutil import which

from .. import settings


class AgyError(RuntimeError):
    pass


def agy_command() -> list[str]:
    cmd = os.environ.get("AGY_CMD") or settings.get().ai.agy_cmd or "agy --headless -p"
    return shlex.split(cmd)


def agy_available() -> bool:
    try:
        return which(agy_command()[0]) is not None
    except (ValueError, IndexError):
        return False


def run_prompt(prompt: str, cwd: Path | None = None) -> str:
    cmd = [*agy_command(), prompt]
    timeout = settings.get().ai.timeout_s
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        )
    except FileNotFoundError as exc:
        raise AgyError(
            f"Antigravity CLI not found ({agy_command()[0]!r}). Install it and "
            "log in once (`agy`), or fix the command in Settings."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise AgyError(f"agy timed out after {timeout}s") from exc
    if out.returncode != 0:
        raise AgyError(f"agy exited {out.returncode}: {(out.stderr or out.stdout).strip()[:400]}")
    return out.stdout
