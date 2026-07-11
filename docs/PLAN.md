# Video Montage → Premiere Pro Project Generator

## Context

The user records many vacation videos and later builds a music montage in Adobe Premiere Pro. Today that means manually reviewing dozens of clips, picking the good parts, and assembling them against a song. This project builds a **locally-run web app** (empty repo, greenfield) that automates the tedious parts:

1. Scan a local directory of videos, extract frames per video, and have **Gemini (via Antigravity CLI `agy`)** describe, rate, and hashtag each clip.
2. A **review page** where the user previews each video, rates it Lightroom-style (stars + reject), batch-rates multi-selections, and marks the interesting part(s) with in/out points.
3. **Song analysis**: user picks a song; **librosa** locally detects BPM, beats, and section boundaries; Gemini semantically labels the sections (intro, verse, chorus…). (Antigravity CLI does not officially support audio input, so analysis is local — decided with user.)
4. A **montage page**: video bin + multi-track timeline over the song waveform with beat/section markers; clips are placed manually (drag & drop) or **automatically by Claude through an MCP server** exposed by the app.
5. **Export to Premiere Pro** as FCP7 XML (`xmeml` v5) — the stable interchange format Premiere imports directly as a sequence, referencing the original files on disk for final grading/editing.

Decisions confirmed with user: **Python (FastAPI) backend + React (Vite/TS) frontend**, hybrid librosa+Gemini music analysis, **English UI**, advanced in/out selection (dual-handle trim bar, I/O keyboard shortcuts, filmstrip, multiple ranges per video).

## Architecture

```
video-composer-editor/
├── backend/
│   ├── pyproject.toml            # fastapi, uvicorn, sqlalchemy, librosa, soundfile, numpy, mcp, pytest
│   ├── app/
│   │   ├── main.py               # FastAPI app, CORS, static serving of frontend build + media
│   │   ├── db.py                 # SQLAlchemy + SQLite (stored in project workdir)
│   │   ├── models.py             # ORM models (below)
│   │   ├── api/
│   │   │   ├── projects.py       # create/open project, pick video dir & song (server-side dir browser)
│   │   │   ├── videos.py         # list, rate, reject, ranges CRUD, analysis status
│   │   │   ├── music.py          # upload/select song, analysis results, waveform peaks
│   │   │   ├── timeline.py       # tracks & timeline clips CRUD
│   │   │   ├── export.py         # generate + download .xml
│   │   │   └── media.py          # video/proxy/thumbnail/audio serving with HTTP Range support
│   │   ├── services/
│   │   │   ├── scanner.py        # walk dir, ffprobe metadata
│   │   │   ├── frames.py         # ffmpeg frame extraction, thumbnails, filmstrip, proxies
│   │   │   ├── gemini.py         # agy CLI wrapper (subprocess, headless, JSON parsing)
│   │   │   ├── audio_analysis.py # librosa: BPM, beats, section segmentation, waveform peaks
│   │   │   ├── jobs.py           # simple asyncio background job queue with progress
│   │   │   └── xmeml.py          # FCP7 XML (xmeml v5) sequence generator
│   │   └── events.py             # SSE broadcaster so UI reflects MCP/job changes live
│   ├── mcp_server.py             # MCP stdio server (FastMCP) for Claude auto-placement
│   └── tests/                    # xmeml golden-file test, audio analysis smoke, api tests
├── frontend/                     # Vite + React + TypeScript
│   └── src/
│       ├── pages/SetupPage.tsx   # pick directory + song, launch analysis, progress
│       ├── pages/ReviewPage.tsx  # video grid, ratings, detail player with in/out ranges
│       ├── pages/MusicPage.tsx   # waveform, sections (editable labels), beats
│       ├── pages/MontagePage.tsx # bin + multi-track timeline + export button
│       ├── components/           # VideoCard, StarRating, TrimBar, Filmstrip, Waveform, Timeline…
│       └── lib/api.ts, lib/sse.ts
├── README.md                     # setup: ffmpeg, agy auth, run instructions, MCP config for Claude
└── .gitignore
```

Runtime model: one FastAPI process serves the API, the media, and (in prod mode) the built frontend. All derived media (frames, thumbnails, filmstrips, proxies, waveform peaks) is cached under `<video_dir>/.montage-cache/`. Project state lives in `montage.db` (SQLite) in the same cache dir, so a project is self-contained next to the footage. The MCP server is a separate `mcp_server.py` process that opens the same SQLite DB and pokes the API's SSE channel via a local HTTP call so the browser updates live.

## Data model (SQLite)

- `project`: id, name, video_dir, song_path, created_at
- `video`: id, project_id, path, filename, duration, fps, width, height, codec, size, shot_at (from metadata), status(pending/analyzing/ready/error), proxy_path?
- `video_analysis`: video_id, description, ai_score (1–10), hashtags (JSON array), raw_response
- `video_rating`: video_id, stars (0–5), rejected (bool)
- `video_range`: id, video_id, t_in, t_out, label?  (multiple "interesting parts" per video)
- `song`: project_id, path, duration, bpm, beats (JSON array of times), downbeats (JSON)
- `song_section`: id, start, end, label (intro/verse/chorus/bridge/outro…), source (ai/user)
- `track`: id, index, name  (timeline rows)
- `timeline_clip`: id, track_id, video_id, timeline_start, source_in, source_out, placed_by (user/claude)

## Implementation phases

### Phase 1 — Scaffolding & ingestion
- Backend + frontend skeletons, dev proxy, SQLite setup.
- Setup page: server-side directory browser (list dirs/files via API — browsers can't hand over local paths), pick video folder and song file.
- `scanner.py`: find `*.mp4|mov|m4v|avi|mts|3gp` etc., `ffprobe -print_format json` for metadata.
- `frames.py`:
  - Analysis frames: `ffmpeg -ss <t> -i <file> -frames:v 1` at N evenly spaced timestamps; N = clamp(3 + duration//5, 3, 10).
  - Grid thumbnail + **filmstrip strip** (one wide JPEG of ~20 tiles) for the trim UI.
  - **Playback proxy**: if codec is browser-unfriendly (HEVC/H.265, MPEG-2, 10-bit), transcode a 720p H.264 proxy in the background; otherwise serve the original. `media.py` implements HTTP Range responses for scrubbing.
- `jobs.py`: asyncio queue with bounded concurrency (ffmpeg jobs ~2, agy jobs ~2), progress reported over SSE.

### Phase 2 — Gemini analysis via Antigravity CLI
- `gemini.py` invokes `agy` non-interactively per video:
  `agy -p "<prompt> @frame1.jpg @frame2.jpg …"` (command template configurable via env `AGY_CMD` since flags may evolve; docs: `-p/--prompt` triggers non-interactive mode, `@file` pulls files into context, images are officially supported).
- Prompt asks for **strict JSON**: `{"description": "...", "score": 1-10, "hashtags": ["beach","sunset","people"], "highlights": [{"frame": 2, "reason": "..."}]}`. Parse defensively (extract first JSON object from output); on failure retry once, then mark video `error` (user can re-run or edit manually).
- Store in `video_analysis`; hashtags are also editable in the UI.
- Graceful degradation: if `agy` is not installed/authenticated, the app still works — analysis fields stay empty and everything manual still functions. README documents `agy` install + one-time OAuth login.

### Phase 3 — Review page
- Grid of `VideoCard`s: thumbnail, duration, AI description + score + hashtag chips, star widget.
- **Ratings**: 0–5 stars + reject flag (Lightroom-style). Keyboard: `1..5` stars, `0` clear, `X` reject. Click-select, Shift/Ctrl multi-select, rating applies to the whole selection. Filter bar: min stars, hide rejected, hashtag filter, sort by AI score.
- **Detail view** (modal or side panel): `<video>` player of proxy/original; below it the **TrimBar** — filmstrip background with draggable in/out handles; `I`/`O` set in/out at playhead; "Add range" allows multiple ranges per video; ranges listed with delete/label. Loop-play the active range.

### Phase 4 — Music analysis
- `audio_analysis.py` (librosa): `beat_track` → BPM + beat times; downbeats estimated from beat phase; **structural segmentation** via `librosa.segment.agglomerative`/spectral clustering on chroma+MFCC to get section boundaries; per-section RMS energy.
- Waveform peaks JSON (min/max per ~2000 buckets) for canvas rendering.
- Gemini labeling: send Gemini (text-only `agy -p`) the section table (start/end/energy/repetition structure) and ask it to label sections (intro/verse/chorus/bridge/outro) as JSON. Purely additive — labels are editable and sections can be split/merged/renamed on the Music page.

### Phase 5 — Montage page + timeline
- Left: **bin** of non-rejected videos (sorted by stars desc, then AI score), showing per-video selected ranges as draggable items.
- Right/bottom: **Timeline** (custom canvas/DOM component):
  - Ruler in seconds; audio row rendering waveform + beat ticks + colored section bands with labels.
  - 2–4 video tracks (add-track button). Drag a video/range from bin → creates `timeline_clip`; drag to move, edge-drag to trim (bounded by source duration); **snapping** to beats and section boundaries (toggleable); overlap on the same track is rejected (clips shove/clamp).
  - Click clip → small inspector (source range, nudge, delete). Zoom with wheel, space = play preview (audio playback + jump-cut video preview of the clip under the playhead — best-effort preview, not frame-accurate rendering).
- State syncs over the REST API; SSE pushes external changes (from MCP) into the UI live.

### Phase 6 — MCP server for Claude auto-placement
- `mcp_server.py` with the official Python MCP SDK (FastMCP, stdio transport). Tools:
  - `get_project_summary()` — song duration/BPM, sections, track list
  - `list_videos(min_stars, include_unrated, hashtag)` — id, description, hashtags, stars, AI score, duration, selected ranges
  - `get_music_sections()` / `get_beats(start, end)`
  - `get_timeline()` — current clips per track
  - `place_clip(video_id, track, timeline_start, source_in, source_out)` — validates overlap/bounds
  - `move_clip(clip_id, timeline_start, track)` / `remove_clip(clip_id)` / `clear_track(track)`
- Claude (Claude Code/Desktop) connects via `claude mcp add montage -- python backend/mcp_server.py --project <dir>`; README includes the config snippet and a suggested prompt ("place my 4–5★ clips on the chorus, cut on beats…"). Auto mode = the user asks Claude; the app just exposes the tools and live-updates the UI.

### Phase 7 — Premiere Pro export (xmeml v5)
- `xmeml.py` generates `<xmeml version="5">` with one `<sequence>`:
  - Sequence rate from the dominant video FPS (fallback 25); NTSC flag handled for 29.97/23.976.
  - One `<video><track>` per timeline row, `<clipitem>` per clip with `start/end` (timeline frames) and `in/out` (source frames), `<file>` with `pathurl` = `file://localhost/...` percent-encoded absolute path, per-file `rate` and dimensions from ffprobe.
  - One stereo `<audio><track>` with the full song as a single clipitem.
  - Frame math: all times stored in seconds → converted with rational fps; mixed-fps sources rely on Premiere's conform-on-import (standard xmeml behavior).
- Export button downloads `montage.xml`; README documents File → Import in Premiere and relinking if the drive letter/mount differs.
- **Golden-file test**: known timeline fixture → exact expected XML; plus schema sanity checks (frame counts, path encoding, track counts).

## Key technical notes

- `agy` auth is OAuth-interactive on first run — done once by the user in a terminal; the app only shells out afterwards. Command template configurable (`AGY_CMD` env) to survive CLI flag changes.
- Directory/file pickers are server-side (API lists the filesystem) because a browser cannot give a web app real local paths — and real paths are required for the Premiere XML.
- All heavy work (ffmpeg, librosa, agy) runs in the background job queue with SSE progress so the UI never blocks.
- `.gitignore`: `node_modules`, `dist`, `__pycache__`, `.venv`, `*.db`, `.montage-cache/`.

## Verification

1. `cd backend && pip install -e . && uvicorn app.main:app` + `cd frontend && npm i && npm run dev` — app boots.
2. Generate test fixtures locally with ffmpeg (`testsrc`/`smptebars` clips of varied durations + a synthesized tone/beat WAV) into a temp dir; run the full flow: scan → frames extracted → (agy mocked via `AGY_CMD=./tests/fake_agy.sh` returning canned JSON, since the sandbox has no Google auth) → rate/reject/ranges in the UI → librosa analysis on the WAV → place clips on the timeline → export XML.
3. `pytest backend/tests`: xmeml golden-file comparison, audio analysis returns beats/sections on the synthetic track, API CRUD, overlap validation.
4. MCP: run `mcp_server.py` and exercise tools with a scripted MCP client (list videos, place clip) and confirm the clip appears via `get_timeline` + in the DB and SSE fires.
5. Frontend build passes `tsc` + `npm run build`; drive the UI with Playwright (pre-installed Chromium) for the review-page rating and timeline drag smoke test.
6. Final check the user does on their machine: import the exported `montage.xml` into Premiere Pro and confirm the sequence, clips, and song appear correctly linked.
