# 🎬 Video Montage Composer

Turn a folder of vacation videos + a song into an **Adobe Premiere Pro** project.

A locally-run web app that:

1. **Scans** a folder of videos, extracts frames, thumbnails, filmstrips and browser-playable proxies (ffmpeg).
2. **Analyzes every clip with AI**: description, 1–10 score, and hashtags — via Google's [Antigravity CLI](https://antigravity.google/product/antigravity-cli) (`agy`, Gemini) or any **OpenAI-compatible endpoint** (z.ai GLM, OpenAI, OpenRouter, Ollama…), selectable on the in-app Settings page.
3. Lets you **review and rate** clips Lightroom-style (0–5 stars, reject flag, batch rating, keyboard shortcuts) and mark the interesting part(s) of each clip with in/out points over a filmstrip.
4. **Analyzes your song locally with librosa** (BPM, beats, structure sections) and asks Gemini to label the sections (intro / verse / chorus / …).
5. Gives you a **montage page**: video bin + multi-track timeline over the song waveform, with snapping to beats and sections. Place clips by hand — or let **Claude place them automatically through the built-in MCP server**.
6. **Exports FCP7 XML (`xmeml` v5)** that Premiere Pro imports directly as a sequence linked to your original files, ready for final editing and color grading.

## Preparing the environment

Everything runs on **your own machine** (the app needs direct access to your video
files, ffmpeg and the `agy` CLI). You need:

| Tool | Version | Used for |
|---|---|---|
| Python | 3.10+ | backend, librosa music analysis, MCP server |
| Node.js | 20+ | building the React frontend |
| ffmpeg + ffprobe | any recent | frames, thumbnails, proxies, metadata |
| AI provider | — | clip analysis (optional): Antigravity CLI (`agy`) **or** an OpenAI-compatible endpoint (z.ai GLM…) |
| Claude Code / Claude Desktop | latest | only if you want AI auto-placement via MCP (optional) |

### 1. Base tools

**macOS** (with [Homebrew](https://brew.sh)):

```bash
brew install python@3.12 node ffmpeg git
```

**Windows** (PowerShell, with winget):

```powershell
winget install Python.Python.3.12 OpenJS.NodeJS.LTS Gyan.FFmpeg Git.Git
```

**Ubuntu/Debian:**

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nodejs npm ffmpeg git
```

Verify: `python3 --version`, `node --version`, `ffmpeg -version` all work in a new terminal.

### 2. AI provider (optional)

Without one, everything works except AI descriptions/scores/hashtags and AI
section labels. Two options, selectable on the in-app **Settings** page:

**Option A — OpenAI-compatible endpoint (e.g. z.ai GLM).** Nothing to install:
open **Settings** in the app and fill in the base URL, an image-capable model
and your API key. For z.ai GLM: API plan → base URL `https://api.z.ai/api/paas/v4`
(model `glm-4.6v-flash`); **Coding Plan** → base URL
`https://api.z.ai/api/coding/paas/v4` (model `glm-4.7` / `glm-4.6v`, images
supported). Local endpoints (Ollama, LM Studio) work too. Use **Save & test AI**
to validate.

**Option B — Antigravity CLI (Gemini).** Official installers (see
[antigravity.google/docs/cli-install](https://antigravity.google/docs/cli-install)):

```bash
# macOS / Linux
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

```powershell
# Windows (PowerShell)
irm https://antigravity.google/cli/install.ps1 | iex
```

Then, in a **new terminal**:

```bash
agy          # first run opens the browser to sign in with your Google account
```

Sign in once; after that the app can call `agy` non-interactively on its own.
Check it works with a quick `agy -p "say hi"`.

Notes:

- `agy` must be reachable from the shell that launches the backend. If it lives
  somewhere unusual or its flags change, override the command template:
  `AGY_CMD="/path/to/agy -p"`.
- The AI analysis sends a few JPEG frames per video to Google. Skip installing
  `agy` if you don't want that.

### 3. This app

```bash
git clone https://github.com/dmuniesa/video-composer-editor.git
cd video-composer-editor

# backend (Python virtualenv)
cd backend
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\pip install -e ".[dev]"

# frontend (build once, served by the backend)
cd ../frontend
npm install
npm run build
```

The first `pip install` takes a few minutes (librosa pulls in numba/llvmlite).

### Alternative: conda

If you use [conda/miniconda](https://docs.conda.io), one environment covers
step 1 (Python, Node **and** ffmpeg come from conda-forge) and the backend
install — you only need conda + git preinstalled:

```bash
git clone https://github.com/dmuniesa/video-composer-editor.git
cd video-composer-editor
conda env create -f environment.yml
conda activate video-montage

cd frontend && npm install && npm run build && cd ..
```

With the environment active, run the server with plain `uvicorn` (no `.venv/bin/`
prefix), and register the MCP server with `python backend/mcp_server.py ...`.
The Antigravity CLI (step 2) is installed the same way in both setups.

### 4. (Optional) Claude for auto-placement

Install [Claude Code](https://claude.com/claude-code) (`npm install -g @anthropic-ai/claude-code`)
or Claude Desktop, then register the MCP server as described in
[Let Claude build the montage](#let-claude-build-the-montage-mcp) below.

## Run

```bash
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8765
```

Open <http://127.0.0.1:8765> — the built frontend is served by the backend.

For frontend development, run `npm run dev` in `frontend/` (Vite on :5173 proxies to :8765).

If the `agy` binary lives somewhere unusual or its flags change, override the
command template: `AGY_CMD="/path/to/agy -p" uvicorn ...`

## Workflow

📖 **Full user manual with screenshots: [docs/MANUAL.md](docs/MANUAL.md)** — also
available inside the app under the **Guide** tab.

| Page | What you do |
|---|---|
| **Setup** | Browse to your video folder → the app scans it and queues frame extraction + AI analysis. Pick the song here too. |
| **Review** | Grid of clips with AI description/score/hashtags. Click to select (Shift/Ctrl for multi), **1–5** to rate, **0** to clear, **X** to reject. Double-click opens the player: **I**/**O** set in/out at the playhead, **Enter** saves the range, **L** loop-plays it. A clip can have several ranges. |
| **Music** | Waveform, BPM, beats and structure sections. Fix labels, split at the playhead, or merge sections. |
| **Montage** | Drag clips (or their ranges) from the bin onto the tracks. Drag to move, edge-drag to trim, snapping to beats/sections (**S** toggles). **Space** previews audio + a jump-cut video preview. **Del** removes the selected clip. |
| **Export** | "Export to Premiere" downloads `montage.xml`. In Premiere: **File → Import**, and the sequence appears with your clips and the song, linked to the original files. Relink if your media moved. |

All derived media and the project database live in `<your video folder>/.montage-cache/` — delete that folder to reset a project.

## Let Claude build the montage (MCP)

The app ships an MCP server that exposes the project to Claude:

```bash
claude mcp add montage -- /abs/path/backend/.venv/bin/python /abs/path/backend/mcp_server.py --project /path/to/video/folder
```

Tools: `get_project_summary`, `list_videos`, `get_music_sections`, `get_beats`,
`get_timeline`, `place_clip`, `move_clip`, `remove_clip`, `clear_track`.
Track numbers are 0-based indexes; rejected videos are never listed.

Then ask Claude, for example:

> Build a montage: put my 4–5 star clips on the choruses and high-energy
> sections, calmer clips on the verses, prefer each video's hand-picked
> ranges, cut on the beat, and don't repeat a clip.

Keep the web app open: clips placed by Claude appear on the timeline live (purple).

## Or let agy / GLM build the montage (in-app)

Claude via MCP is not the only option: in **Settings → Composer provider** you
can pick the **Antigravity CLI (agy)** or any **OpenAI-compatible endpoint**
(e.g. z.ai GLM Coding Plan) instead — they reuse the credentials from the AI
provider section. The Montage page then shows an **Auto-compose** panel: write
your instructions (same style as the Claude prompt above) and the whole project
(videos, song sections, beats, current timeline) is sent as a single prompt;
the model replies with clip placements that are validated and applied, live.
Clips placed this way are purple too, tagged with the provider name. With the
provider set to *Claude via MCP* (the default) the button stays disabled and
composing works through Claude as before.

## Tests

```bash
cd backend && .venv/bin/python -m pytest tests/
```

The suite generates fixture media with ffmpeg and fakes the Antigravity CLI
(`tests/fake_agy.py`), so it runs without a Google account. Includes a
golden-file test for the Premiere XML.

## Notes & limitations

- Antigravity CLI does not officially support audio input, so music analysis is
  local (librosa) and Gemini only labels the sections from the extracted data.
- The timeline preview is best-effort (jump cuts, not frame-accurate rendering) —
  the real render happens in Premiere.
- HEVC/10-bit clips get a 720p H.264 proxy for browser playback; the exported
  XML always references the **original** files.

See [docs/PLAN.md](docs/PLAN.md) for the full design document.
