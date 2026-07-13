"""Native OS folder/file picker.

The dialog is opened in a short-lived subprocess so Tk never runs on the
server's worker threads (Tk is not thread-safe) and a Tk crash can't take the
server down. Works because this is a local app: the server shares the user's
desktop session. Falls back gracefully (available() -> False) where Tk isn't
installed, e.g. a headless Linux box without python3-tk.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_TIMEOUT = 600  # a dialog left open shouldn't hang the worker forever


def available() -> bool:
    try:
        import tkinter  # noqa: F401

        return True
    except Exception:
        return False


def pick(kind: str, initial: str = "", title: str = "") -> str | None:
    """Open a native dialog and return the chosen absolute path, or None if the
    user cancelled (or the dialog timed out). kind is 'dir' or 'audio'."""
    try:
        out = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), kind, initial, title],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    path = out.stdout.strip()
    return path or None


def _run_dialog(kind: str, initial: str, title: str) -> str:
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        if kind == "audio":
            return filedialog.askopenfilename(
                title=title or "Choose song",
                initialdir=initial or None,
                filetypes=[
                    ("Audio", "*.mp3 *.wav *.m4a *.aac *.flac *.ogg *.aiff"),
                    ("All files", "*.*"),
                ],
            ) or ""
        return filedialog.askdirectory(
            title=title or "Choose folder", initialdir=initial or None, mustexist=False
        ) or ""
    finally:
        root.destroy()


if __name__ == "__main__":
    _kind = sys.argv[1] if len(sys.argv) > 1 else "dir"
    _initial = sys.argv[2] if len(sys.argv) > 2 else ""
    _title = sys.argv[3] if len(sys.argv) > 3 else ""
    sys.stdout.write(_run_dialog(_kind, _initial, _title))
