import { useEffect } from 'react'
import { Link, useLocation } from 'react-router-dom'

const TOC = [
  ['overview', 'Overview'],
  ['setup', '1 · Create a project'],
  ['review', '2 · Review & rate'],
  ['people', '3 · People in your clips'],
  ['ranges', '4 · Mark the best parts'],
  ['music', '5 · Analyze the song'],
  ['montage', '6 · Build the montage'],
  ['ai-compose', '7 · AI auto-placement'],
  ['export', '8 · Export your montage'],
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
  ['Detail', 'L', 'Loop-play the selected range (toggle)'],
  ['Detail', '← / →', 'Nudge the playhead one frame (paused)'],
  ['Detail', 'Shift + ← / →', 'Previous / next clip'],
  ['Detail', 'Space', 'Play / pause'],
  ['Montage', 'Space', 'Play / pause the montage preview'],
  ['Montage', '← / →', 'Move the playhead one frame'],
  ['Montage', 'Shift + ← / →', 'Scroll the timeline'],
  ['Montage', 'S', 'Toggle snap to beats, sections & clip edges'],
  ['Montage', 'Del', 'Delete the selected clip (leaves a gap)'],
  ['Montage', 'Shift + Del', 'Ripple delete — remove the clip and close the gap'],
  ['Montage', 'Ctrl + Z', 'Undo the last timeline edit'],
  ['Montage', 'Ctrl + Shift + Z / Ctrl + Y', 'Redo'],
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
          A project has a <b>storage folder</b> you choose and one or more <b>source folders</b> of
          footage. All of its state (AI descriptions, your stars and rejects, in/out ranges, the
          song analysis, the timeline) lives in a small database inside{' '}
          <code>&lt;storage&gt;/.montage-cache/</code> — <b>separate from the footage</b>, so the
          same project can pull clips from several folders on different drives. You can close the
          browser or the server anytime and pick up exactly where you left off, work on two
          projects in two tabs, add or remove source folders, or <b>repoint</b> one that moved
          without losing any clip&apos;s data. Deleting <code>.montage-cache/</code> resets the
          project; copying it backs the montage up (and it can be <b>imported</b> elsewhere). Your
          original video files are never modified.
        </p>
        <p>
          The typical flow is the order of the tabs: <b>Setup → Review → Music → Montage</b>, then
          export. Background work (frame extraction, AI analysis, proxies) shows in the status bar
          at the bottom; you don&apos;t need to wait for it to move on.
        </p>

        <h2 id="setup">1 · Create a project (Setup)</h2>
        <p>
          From the home screen, click <b>New project</b>. On the page that opens, click{' '}
          <b>Choose folder…</b> — your operating system&apos;s native dialog appears — to pick a{' '}
          <b>storage folder</b> for the project (where its database lives; it can be empty and
          separate from your footage), optionally set a name, and hit <b>Create project</b>. Then,
          on the Setup page, use the <b>Source folders</b> panel to <b>Add folder</b> for each
          folder of footage (the same native dialog). Each source is scanned recursively (<code>.mp4</code>,{' '}
          <code>.mov</code>, <code>.mts</code>, <code>.mkv</code>…), read with ffprobe; frames, a
          thumbnail and a filmstrip are extracted per clip and browser-friendly proxies are
          transcoded for formats like HEVC/10-bit. If an AI provider is configured, every clip also
          gets a description, a 1–10 score and hashtags — plus mood, energy and scene context
          (each aspect can be toggled in Settings). Two clips with the same name in different
          source folders coexist without clashing.
        </p>
        <ul>
          <li>
            <b>Add folder</b> attaches another source; <b>✕</b> removes one (its clips leave the
            project — the files on disk are untouched).
          </li>
          <li>
            <b>Repoint…</b> relinks a source folder that moved to a new location, keeping every
            clip&apos;s analysis, ratings, ranges and timeline placement.
          </li>
          <li>
            <b>Rescan all</b> picks up files you added to or removed from any source later.
          </li>
          <li>
            <b>Analyze all with AI</b> re-queues AI analysis (e.g. after configuring a provider).
          </li>
          <li>
            Pick your <b>song</b> in the bottom panel — music analysis starts right away.
          </li>
        </ul>
        <p>
          Already have a project from another machine or backup? On the home screen click{' '}
          <b>Import project</b> and pick its storage folder (the one containing{' '}
          <code>.montage-cache/</code>) to re-register it with everything intact.
        </p>

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
            Filter with the top bar: free-text <b>search</b> (matches filename, description, tags
            and people; start with <code>#</code> to search hashtags only, <code>@</code> for
            people only), <b>subfolder</b>, minimum stars, hide rejected, sort by name / AI score
            / stars / duration — and click any <b>#hashtag</b> or <b>@person</b> chip to filter by
            it.
          </li>
        </ul>
        <div className="callout">
          Suggested workflow: sort by <b>AI score</b>, reject the junk with <kbd>X</kbd>, then give
          4–5 stars to the must-haves.
        </div>

        <h2 id="people">3 · People in your clips (People)</h2>
        <p>
          The <b>People</b> tab detects the people appearing in your footage — entirely on your
          machine, nothing is uploaded. It needs the optional face libraries (
          <code>pip install -e &quot;.[faces]&quot;</code> in <code>backend/</code>; the page shows
          the exact hint when they&apos;re missing), and the first detection downloads the face
          model (~280 MB) once.
        </p>
        <ul>
          <li>
            Press <b>Detect people</b>: every clip is sampled (one frame every ~2 s) and each face
            gets an identity fingerprint. Similar faces are <b>grouped automatically</b>; groups
            appear unnamed at the bottom.
          </li>
          <li>
            <b>Type a name</b> on a group (&quot;Ana&quot;, &quot;abuelo&quot;…) to identify that
            person. Typing a name that <b>already exists merges</b> the two groups — the quickest
            way to fix the same person split in two.
          </li>
          <li>
            Named people are matched <b>automatically</b> when you detect faces in new clips, and
            the matching <b>learns</b>: every face confirmed for a person covers another
            pose/lighting, making future matches easier.
          </li>
          <li>
            Open <b>Faces</b> on a card (the face count is clickable too): <b>click a face</b> to
            view it large — the full frame with the face highlighted — and <b>👁</b> opens the
            video at that exact moment in a new tab. <b>📌</b> makes a face the card&apos;s cover
            picture, <b>↷</b> detaches a mis-grouped face and <b>🚫</b> ignores a false positive.{' '}
            <b>Merge into…</b> joins whole groups; <b>♻ Re-cluster</b> re-groups the unassigned
            faces (named people are never touched).
          </li>
          <li>
            <b>Hide</b> an unnamed group you&apos;re not interested in (strangers in the
            background): it moves to a collapsed <b>Hidden</b> section, but its faces are kept —
            new detections keep matching it instead of creating new unnamed groups. Unhide it
            anytime.
          </li>
          <li>
            Named people show as <b>@name</b> chips on the Review cards (click to filter, or search{' '}
            <code>@name</code>), and both the in-app AI composer and Claude over MCP see who
            appears in each clip — so &quot;only clips with Ana&quot; works as a montage
            instruction.
          </li>
          <li>
            If a clip already has named people when you run (or re-run) its AI analysis, the
            description uses their names (&quot;Ana diving off the boat&quot;). Detection order
            doesn&apos;t matter: name people first and then analyze, or just <b>Re-analyze</b>{' '}
            later. Toggleable in Settings.
          </li>
        </ul>

        <h2 id="ranges">4 · Mark the best parts</h2>
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
            Each saved range row has <b>▶</b> (play it once) and <b>🔁</b> (loop it) — both are
            toggles that stop when clicked again — plus an editable label and <b>✕</b> to delete.
            Drag the blue handles of a saved range to fine-tune it; <kbd>L</kbd> loop-plays the
            selected range.
          </li>
          <li>
            <kbd>←</kbd>/<kbd>→</kbd> nudge the playhead <b>one frame</b> (paused) for precise
            in/out points; <kbd>Shift</kbd>+<kbd>←</kbd>/<kbd>→</kbd> jump to the previous/next
            clip.
          </li>
          <li>
            You can also edit the AI description and hashtags here. Below the description, badges
            show the AI&apos;s <b>mood</b>, <b>energy</b> (motion level) and <b>scene</b>{' '}
            (setting / time of day / shot type) — the composer uses them to match clips to the
            music. Each aspect can be turned off in Settings if your provider handles it poorly.
          </li>
          <li>
            A <b>Clip info</b> panel beside the analysis lists the technical metadata read from the
            file&apos;s container tags — capture date, <b>camera</b> make/model, <b>lens</b>,{' '}
            <b>software</b> and <b>location</b> (GPS) when present. The composer also gets the
            capture time, camera and lens to keep time-of-day and camera continuity.
          </li>
        </ul>
        <p>
          Saved ranges become draggable items in the montage bin, and the AI composer prefers them
          when auto-placing clips.
        </p>
        <p>
          With the analysis media set to <b>Video</b> (Settings, agy only), the AI also proposes{' '}
          <b>suggested moments</b> — time ranges with a reason, shown in the AI analysis panel.
          Press <b>▶</b> to preview one and <b>＋</b> to save it as a normal range you can edit;
          your own ranges always take priority.
        </p>

        <h2 id="music">5 · Analyze the song (Music)</h2>
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

        <h2 id="montage">6 · Build the montage</h2>
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
            <b>Right-click</b> a clip in the bin for quick actions: place it (or one of its
            ranges) at the playhead, open its detail (player, ranges, tags), jump to it in
            Review, rate it or reject it. <b>Double-click</b> opens the detail directly.
          </li>
          <li>
            <b>Filter the bin</b> with the box at the top: free text, <code>#hashtag</code>, or a
            subfolder of your project — handy on big shoots.
          </li>
          <li>
            Drag a clip horizontally to move it, vertically to change tracks, and drag its{' '}
            <b>edges</b> to trim.
          </li>
          <li>
            <b>Snap</b> (<kbd>S</kbd>) magnetizes moves, trims and drops to beats, section
            boundaries <b>and the edges of neighbouring clips</b> — so clips butt together with
            no black gap between them (like Premiere&apos;s magnet). Both the clip&apos;s left and
            right edge are magnetic, so it also clicks into the far side of a gap you&apos;re
            filling.
          </li>
          <li>
            Left a gap anyway? <b>Right-click the empty space</b> on a track and choose{' '}
            <b>Close gap</b> — the next clip (and everything after it) slides left to butt against
            the clip in front.
          </li>
          <li>
            Clips can&apos;t overlap on a track — add tracks (<b>+ track</b>) to layer
            alternatives or B-roll. Higher tracks sit on top in Premiere.
          </li>
          <li>
            Click a clip to select it (the inspector at the bottom shows exact times).{' '}
            <kbd>Del</kbd> removes it and leaves a gap; <kbd>Shift</kbd>+<kbd>Del</kbd> (or{' '}
            <b>Ripple delete</b> in the clip&apos;s right-click menu) removes it and pulls the
            following clips left to close the gap.
          </li>
          <li>
            <kbd>Space</kbd> plays the song with a best-effort jump-cut preview. The
            frame-accurate result comes later in Premiere.
          </li>
        </ul>

        <h2 id="ai-compose">7 · AI auto-placement</h2>
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
          Both composers see everything the analysis produced: descriptions, hashtags, scores,
          star ratings, saved ranges, named people — and, when enabled, mood/energy/scene and the
          AI-suggested highlight ranges, used to put high-energy clips on the chorus, calm scenic
          ones on intros and instrumental passages, vary shot types, and cut long clips at their
          best moment.
        </p>
        <p>
          Clips placed by an AI appear <b>purple</b> on the timeline, live. You can drag, trim or
          delete them like any other clip.
        </p>

        <h2 id="export">8 · Export your montage</h2>
        <p>
          Click <b>Export</b> (top right of the Montage tab) and pick your editor. All three
          exports reference your <b>original</b> files on disk, with every cut at the right frame
          and the song on the audio tracks:
        </p>
        <ul>
          <li>
            <b>Premiere Pro</b> — downloads <code>montage.xml</code> (FCP7 XML). In Premiere:{' '}
            <b>File → Import</b>; a bin appears with the sequence.
          </li>
          <li>
            <b>DaVinci Resolve</b> — downloads <code>montage-resolve.xml</code> (same FCP7 XML,
            which Resolve reads natively). In Resolve: <b>File → Import → Timeline</b>.
          </li>
          <li>
            <b>Final Cut Pro</b> — downloads <code>montage.fcpxml</code> (FCPXML). In Final Cut:{' '}
            <b>File → Import → XML</b>. Video tracks arrive as connected clips above the primary
            storyline (track 1 = lane 1) with the song underneath, keeping the exact positions.
          </li>
        </ul>
        <p>
          If clips show offline (different drive letter/mount), relink them: <b>Link Media</b> in
          Premiere, <b>Relink Media</b> in Resolve, or <b>File → Relink Files</b> in Final Cut.
          From there, finish it in your editor: transitions, color grading, reframes, audio mix.
        </p>

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
            stream. Fix or remove the file and <b>Rescan all</b>.
          </li>
          <li>
            <b>A source folder shows ⚠ &quot;not found&quot;</b> — the folder was moved or its drive
            isn&apos;t mounted. Click <b>Repoint…</b> on that source and pick its new location; the
            clips keep all their data.
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
            <code>mcp_server.py</code> must be exactly the project&apos;s storage folder (the one
            containing <code>.montage-cache/</code>).
          </li>
          <li>
            <b>Reset a project</b> — delete <code>&lt;storage&gt;/.montage-cache/</code> and add
            your source folders again (ratings, ranges and the timeline live there too, so export
            first if you care).
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
          <img src="/favicon.svg" alt="" className="brand-icon" />
          Beatcut
        </Link>
        <span className="spacer" />
        <Link to="/">Home</Link>
        <Link to="/settings">Settings</Link>
      </nav>
      <main className="app-main">{content}</main>
    </div>
  )
}
