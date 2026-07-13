# Testing environment

Local dev/test environment for this repo (already provisioned on this machine:
Python 3.13, Node 22, ffmpeg 7.1 — all installed natively, no conda needed
even though conda is available; see the note at the bottom).

## Activate the environment

**Backend (Python virtualenv)** — from the repo root:

```powershell
# PowerShell
backend\.venv\Scripts\Activate.ps1
```

```bash
# Git Bash / WSL
source backend/.venv/Scripts/activate
```

You'll see `(.venv)` in the prompt once active. Deactivate with `deactivate`.

Without activating, you can still call the venv's binaries directly with a
path prefix, e.g. `backend\.venv\Scripts\python`, `backend\.venv\Scripts\pytest`,
`backend\.venv\Scripts\uvicorn` — this is what CI / one-off commands should use
instead of relying on shell activation.

**Frontend** — no activation needed, just run `npm` commands inside `frontend/`
(dependencies are in `frontend/node_modules`, already installed).

## Run the app

```powershell
cd backend
.venv\Scripts\uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765> — the backend serves the already-built frontend
(`frontend/dist`, built via `npm run build`).

For frontend live-reload during UI work, run in a second terminal:

```powershell
cd frontend
npm run dev
```

Vite serves on :5173 and proxies API calls to :8765 — keep both running.

## Run the test suite

```powershell
cd backend
.venv\Scripts\python -m pytest tests/
```

The suite generates fixture media with ffmpeg and fakes the Antigravity CLI
(`tests/fake_agy.py`) — no AI provider or Google account needed to run it.
Includes a golden-file test for the Premiere XML export
(`tests/golden_montage.xml`). The lyrics tests (`tests/test_lyrics.py`)
monkeypatch the Whisper transcription and use the fake agy for the Antigravity
engine, so `faster-whisper` does not need to be installed to run them — it's
only required to actually use the Whisper engine (Settings → Music analysis).

Useful flags: `-k <name>` to filter, `-x` to stop on first failure, `-v` for
verbose output.

**Known Windows caveat (not a code bug, pre-existing test-infra gap):**

- `test_xmeml.py::test_matches_golden_file` — the golden file encodes
  Unix-style `file://` paths; on Windows the exporter emits drive-letter
  paths (`localhost///C:/media/...`), so the byte-for-byte comparison fails.

Everything else (26 of 27 tests) passes clean on native Windows. (The fake
Antigravity CLI used to be a bash script whose Windows path broke under
`shlex.split`, failing 3 more tests here — it is now `tests/fake_agy.py`,
invoked with the running Python interpreter, so it works on any OS.)

## Rebuilding after changes

- Backend code changes: just restart uvicorn (or add `--reload` to the
  uvicorn command for auto-restart on file changes).
- Frontend code changes: re-run `npm run build` in `frontend/` to refresh
  what uvicorn serves at :8765, or use `npm run dev` (:5173) while iterating.

## AI provider (optional, not required for testing)

Everything above works without any AI provider configured — clip
description/score/hashtags and AI section labels are simply skipped. To test
that path, configure one from the in-app **Settings** page (OpenAI-compatible
endpoint or the Antigravity CLI `agy`) — see the main [README](../README.md#2-ai-provider-optional).

**Status on this machine:** `agy` v1.1.1 is installed at
`%LOCALAPPDATA%\agy\bin\agy.exe` (via the official install script) and is
already authenticated — no manual Google sign-in was needed, it appears to
share auth with the already-installed Antigravity IDE. **Open a new
terminal** so `%LOCALAPPDATA%\agy\bin` (added to the user PATH by the
installer) takes effect.

**Fixed: command-template version drift.** The current `agy` CLI (v1.1.1) has
**no `--headless` flag** (`agy --headless -p "..."` errors with `flags
provided but not defined: -headless`) — only `-p`/`--print` is needed for
non-interactive mode. The app's default `agy_cmd` was `"agy --headless -p"`
in both the `Settings` model default (`backend/app/settings.py`) and the
`gemini.py` fallback; both now default to `"agy -p"`, and the README /
Settings-page placeholder were updated to match. Existing installs with a
persisted `settings.json` (`~/.video-montage-composer/settings.json`) still
have the old value baked in — update it once from the in-app Settings page,
or delete the file to pick up the new default.

Verified end-to-end through the app's own `app.services.gemini.run_prompt()`
— returned a real response, confirming both the auth and the fixed default
command work. Rebuild the frontend after this change
(`cd frontend && npm run build`) since `SettingsPage.tsx`'s placeholder
changed.

**Fixed: descriptions mixed between videos (agy shared scratch).** `agy -p`
does **not** run in the caller's cwd — every invocation executes in one global
scratch dir (`~/.gemini/antigravity-cli/scratch`), and its agent copies
referenced files there. Since every video's frames share the same names
(`frame_00.jpg`…), relative `@frame_00.jpg` refs resolved to stale copies from
whichever analysis ran earlier, so clips got each other's descriptions.
Verified empirically: with a pure-red jpg in the cwd, `agy -p "@frame_00.jpg
color?"` answered "blue" (a stale frame in the scratch). Fix: `ai.py` now
always passes **absolute** paths in `@` refs; re-tested with two concurrent
calls (red/blue) and two real videos analyzed in parallel — no cross-talk.
After updating, re-run analysis on any project whose clips were described
while the bug was live (Library → *Analyze all with Gemini*).

## Resetting a project

All derived media and the per-project database live under the project's storage
folder, `<storage>/.montage-cache/` — delete that folder to reset a project
without touching the original video files (which live in the project's source
folders, decoupled from storage).

## Note on conda

This machine already has conda installed, and the repo's `environment.yml`
offers a one-shot alternative (Python + Node + ffmpeg all from conda-forge)
if native installs of Python/Node/ffmpeg were unavailable:

```bash
conda env create -f environment.yml
conda activate video-montage
cd frontend && npm install && npm run build && cd ..
```

Not needed here since Python/Node/ffmpeg were already present — this repo's
`backend/.venv` was created with the system Python instead. Use conda only if
you want an isolated environment that also pins Node/ffmpeg versions, or if
the `pip install -e ".[dev]"` step fails to build `numba`/`llvmlite` (librosa
dependencies) against the system Python.
