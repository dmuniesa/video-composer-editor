import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'

const TOC = [
  ['overview', 'Overview'],
  ['setup', '1 · Create a project'],
  ['review', '2 · Review & rate'],
  ['ranges', '3 · Mark the best parts'],
  ['music', '4 · Analyze the song'],
  ['montage', '5 · Build the montage'],
  ['ai-compose', '6 · AI auto-placement'],
  ['export', '7 · Export to Premiere'],
  ['settings', 'Settings & AI providers'],
  ['shortcuts', 'Keyboard shortcuts'],
  ['troubleshooting', 'Troubleshooting'],
] as const

const SHORTCUTS: [string, string, string][] = [
  ['Review', '1–5 / 0', 'Rate the selection / clear the rating'],
  ['Review', 'X', 'Toggle reject on the selection'],
  ['Review', 'Esc', 'Clear selection / close the detail view'],
  ['Detail', 'I / O', 'Set in / out point at the playhead'],
  ['Detail', 'Enter', 'Save the drafted range'],
  ['Detail', 'L', 'Loop-play the active range'],
  ['Detail', 'Space', 'Play / pause'],
  ['Montage', 'Space', 'Play / pause the montage preview'],
  ['Montage', 'S', 'Toggle snap to beats & sections'],
  ['Montage', 'Del', 'Delete the selected clip'],
]

export default function GuidePage({ standalone }: { standalone?: boolean }) {
  const { hash } = useLocation()

  useEffect(() => {
    if (!hash) return
    document.getElementById(hash.slice(1))?.scrollIntoView()
  }, [hash])

  const content = (
    <div className="guide-layout">
      <aside className="guide-toc">
        <div className="guide-toc-title">On this page</div>
        {TOC.map(([id, label]) => (
          <a key={id} href={`#${id}`}>
            {label}
          </a>
        ))}
      </aside>

      <article className="guide-content">
        <h1>User guide</h1>
        <p className="lede">
          How to go from a folder of raw videos plus a song to an Adobe Premiere Pro project. The
          whole app runs locally; everything is <b>saved automatically on every action</b> — there
          is no Save button.
        </p>

        <h2 id="overview">Overview</h2>
        <p>
          A project is simply a <b>video folder</b>: all of its state (AI descriptions, your stars
          and rejects, in/out ranges, the song analysis, the timeline) lives in a small database
          inside <code>&lt;folder&gt;/.montage-cache/</code>, next to the footage. That means you
          can close the browser or the server anytime and pick up exactly where you left off, work
          on two projects in two tabs, or move the folder to another drive — the project travels
          with it. Deleting <code>.montage-cache/</code> resets the project; copying it backs the
          montage up. Your original video files are never modified.
        </p>
        <p>
          The typical flow is the order of the tabs: <b>Setup → Review → Music → Montage</b>, then
          export. Background work (frame extraction, AI analysis, proxies) shows in the status bar
          at the bottom; you don&apos;t need to wait for it to move on.
        </p>

        <h2 id="setup">1 · Create a project (Setup)</h2>
        <p>
          From the home screen, click <b>New project</b> and browse to the folder with your
          videos. The app immediately scans it recursively (<code>.mp4</code>, <code>.mov</code>,{' '}
          <code>.mts</code>, <code>.mkv</code>…), reads metadata with ffprobe, extracts frames, a
          thumbnail and a filmstrip per clip, and transcodes browser-friendly proxies for formats
          like HEVC/10-bit. If an AI provider is configured, every clip also gets a description, a
          1–10 score and hashtags.
        </p>
        <ul>
          <li>
            <b>Rescan folder</b> picks up files you added later.
          </li>
          <li>
            <b>Analyze all with AI</b> re-queues AI analysis (e.g. after configuring a provider).
          </li>
          <li>
            Pick your <b>song</b> in the bottom panel — music analysis starts right away.
          </li>
        </ul>

        <h2 id="review">2 · Review &amp; rate your clips</h2>
        <p>
          The <b>Review</b> tab is a Lightroom-style culling grid. Each card shows the thumbnail,
          duration, AI description, hashtags, AI score and your star rating.
        </p>
        <ul>
          <li>
            <b>Hover scrub</b>: move the mouse horizontally over a thumbnail and the clip plays
            under your cursor (left edge = start, right edge = end).
          </li>
          <li>
            <b>Click</b> selects a card; <kbd>Ctrl/Cmd</kbd>-click adds to the selection,{' '}
            <kbd>Shift</kbd>-click selects a range of cards.
          </li>
          <li>
            Press <kbd>1</kbd>–<kbd>5</kbd> to rate the selection, <kbd>0</kbd> to clear,{' '}
            <kbd>X</kbd> to reject. Rejected clips dim out and never reach the montage bin.
          </li>
          <li>
            Filter with the top bar (minimum stars, hide rejected, sort by name / AI score / stars
            / duration) and click any <b>#hashtag</b> to filter by it.
          </li>
        </ul>
        <div className="callout">
          Suggested workflow: sort by <b>AI score</b>, reject the junk with <kbd>X</kbd>, then give
          4–5 stars to the must-haves.
        </div>

        <h2 id="ranges">3 · Mark the best parts</h2>
        <p>
          <b>Double-click</b> a card to open the detail view: a player with a trim bar rendered
          over the clip&apos;s filmstrip.
        </p>
        <ul>
          <li>Click anywhere on the filmstrip to scrub.</li>
          <li>
            <kbd>I</kbd> sets the in point at the playhead, <kbd>O</kbd> the out point,{' '}
            <kbd>Enter</kbd> saves the range. A clip can hold several ranges (&quot;best
            wave&quot;, &quot;kids playing&quot;…).
          </li>
          <li>
            Drag the blue handles of a saved range to fine-tune it; <kbd>L</kbd> loop-plays the
            active range.
          </li>
          <li>You can also edit the AI description and hashtags here.</li>
        </ul>
        <p>
          Saved ranges become draggable items in the montage bin, and the AI composer prefers them
          when auto-placing clips.
        </p>

        <h2 id="music">4 · Analyze the song (Music)</h2>
        <p>
          The <b>Music</b> tab shows what was extracted locally from your track: <b>BPM</b>, every
          beat (yellow ticks are estimated downbeats), the waveform, and the <b>structure
          sections</b> with their relative energy. With an AI provider available the sections come
          pre-labeled (intro / verse / chorus / bridge…).
        </p>
        <ul>
          <li>Change any label with the dropdown.</li>
          <li>
            <b>Split</b> a section at the playhead (click the waveform to position it), or{' '}
            <b>merge</b> a section into its neighbour.
          </li>
          <li>
            <b>Re-analyze</b> re-runs the audio analysis from scratch; <b>Label sections</b>{' '}
            re-asks the AI only for the labels.
          </li>
        </ul>
        <p>
          Good section boundaries matter: they are snap targets on the timeline and the main hint
          the AI composer uses to decide where each kind of clip belongs.
        </p>

        <h2 id="montage">5 · Build the montage</h2>
        <p>
          The <b>Montage</b> tab has the <b>bin</b> on the left (all non-rejected videos, best
          rated first, with their saved ranges) and the <b>timeline</b> on the right: ruler, song
          row (sections + waveform + beat ticks) and your video tracks.
        </p>
        <ul>
          <li>
            <b>Drag</b> a video — or one of its ranges — from the bin onto a track.
          </li>
          <li>
            Drag a clip horizontally to move it, vertically to change tracks, and drag its{' '}
            <b>edges</b> to trim.
          </li>
          <li>
            <b>Snap</b> (<kbd>S</kbd>) magnetizes moves and trims to beats and section boundaries.
          </li>
          <li>
            Clips can&apos;t overlap on a track — add tracks (<b>+ track</b>) to layer
            alternatives or B-roll. Higher tracks sit on top in Premiere.
          </li>
          <li>
            Click a clip to select it (the inspector at the bottom shows exact times);{' '}
            <kbd>Del</kbd> removes it.
          </li>
          <li>
            <kbd>Space</kbd> plays the song with a best-effort jump-cut preview. The
            frame-accurate result comes later in Premiere.
          </li>
        </ul>

        <h2 id="ai-compose">6 · AI auto-placement</h2>
        <p>Two ways to have an AI build the timeline for you:</p>
        <ul>
          <li>
            <b>In-app (Auto-compose)</b>: in <b>Settings → Composer provider</b> pick the
            Antigravity CLI or an OpenAI-compatible endpoint. The Montage tab then shows an{' '}
            <b>Auto-compose</b> panel: write your instructions and the whole project (videos, song
            sections, beats, current timeline) is sent in one prompt; the returned placements are
            validated and applied live.
          </li>
          <li>
            <b>Claude via MCP</b>: the app ships an MCP server that exposes the project to Claude
            Code / Claude Desktop (see the README for the <code>claude mcp add</code> command).
            Ask something like: <i>&quot;Put my 4–5★ clips on the choruses cutting on the beat,
            calmer clips on the verses, prefer saved ranges, don&apos;t repeat clips.&quot;</i>
          </li>
        </ul>
        <p>
          Clips placed by an AI appear <b>purple</b> on the timeline, live. You can drag, trim or
          delete them like any other clip.
        </p>

        <h2 id="export">7 · Export to Premiere Pro</h2>
        <ol>
          <li>
            Click <b>Export to Premiere</b> (top right of the Montage tab) to download{' '}
            <code>montage.xml</code> (FCP7 XML).
          </li>
          <li>
            In Premiere Pro: <b>File → Import</b> and select the file. A bin appears with the
            sequence — every cut at the right frame, the song on the audio tracks, all linked to
            your <b>original</b> files.
          </li>
          <li>
            If clips show offline (different drive letter/mount), select them and use{' '}
            <b>Link Media</b>.
          </li>
        </ol>
        <p>From there, finish it in Premiere: transitions, color grading, reframes, audio mix.</p>

        <h2 id="settings">Settings &amp; AI providers</h2>
        <p>
          The <b>Settings</b> tab configures the whole app (values are global and persist across
          projects). The AI provider analyzes video frames and labels song sections:
        </p>
        <ul>
          <li>
            <b>Auto</b> (default) — uses the Antigravity CLI (<code>agy</code>, Gemini) if
            installed, otherwise the OpenAI-compatible endpoint if configured.
          </li>
          <li>
            <b>OpenAI-compatible endpoint</b> — any service speaking the OpenAI{' '}
            <code>/chat/completions</code> protocol with image input: z.ai GLM, OpenAI,
            OpenRouter, or a fully local Ollama / LM Studio.
          </li>
          <li>
            <b>Disabled</b> — no AI; rating and manual tagging still work.
          </li>
        </ul>
        <p>
          <b>Save &amp; test AI</b> sends a tiny prompt through the selected provider so you can
          validate the key/URL before analyzing hundreds of clips. Privacy note: extracted frames
          are sent to whichever provider you choose — use a local endpoint if you don&apos;t want
          them leaving your machine.
        </p>
        <p>
          The <b>frame extraction</b> section controls how many frames per video are sampled for
          the AI, their resolution, filmstrip tiles and proxy height. Changes apply to newly
          scanned videos; use <b>Re-extract frames for this project</b> (Settings opened from
          inside a project) to regenerate existing ones.
        </p>

        <h2 id="shortcuts">Keyboard shortcuts</h2>
        <table className="guide-table">
          <thead>
            <tr>
              <th>Page</th>
              <th>Key</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {SHORTCUTS.map(([page, key, action], i) => (
              <tr key={i}>
                <td>{page}</td>
                <td>
                  {key.split(' / ').map((k, j) => (
                    <span key={j}>
                      {j > 0 && ' / '}
                      <kbd>{k}</kbd>
                    </span>
                  ))}
                </td>
                <td>{action}</td>
              </tr>
            ))}
          </tbody>
        </table>

        <h2 id="troubleshooting">Troubleshooting</h2>
        <ul>
          <li>
            <b>AI analysis disabled / &quot;agy not found&quot;</b> — the Antigravity CLI
            isn&apos;t on the PATH of the shell that started the server. Install it, run{' '}
            <code>agy</code> once to sign in, restart the server — or configure an
            OpenAI-compatible endpoint in Settings.
          </li>
          <li>
            <b>A video shows status &quot;error&quot;</b> — usually a corrupt file or unsupported
            stream. Fix or remove the file and <b>Rescan</b>.
          </li>
          <li>
            <b>Video won&apos;t play in the browser</b> — proxies are generated in the background;
            wait for the <code>media</code> job in the status bar to finish.
          </li>
          <li>
            <b>Song analysis is slow</b> — the local analysis takes ~10–30 s for a typical song on
            the first run.
          </li>
          <li>
            <b>Claude doesn&apos;t see the project</b> — the <code>--project</code> path passed to{' '}
            <code>mcp_server.py</code> must be exactly your video folder (the one containing{' '}
            <code>.montage-cache/</code>).
          </li>
          <li>
            <b>Reset a project</b> — delete <code>&lt;folder&gt;/.montage-cache/</code> and scan
            again (ratings, ranges and the timeline live there too, so export first if you care).
          </li>
        </ul>
      </article>
    </div>
  )

  if (!standalone) return content
  return (
    <div className="app-shell">
      <nav className="app-nav">
        <Link to="/" className="brand" title="All projects">
          🎬 Beatcut
        </Link>
        <span className="spacer" />
        <Link to="/">Home</Link>
        <Link to="/settings">Settings</Link>
      </nav>
      <main className="app-main">{content}</main>
    </div>
  )
}
