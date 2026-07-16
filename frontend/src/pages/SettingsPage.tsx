import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import type { AppSettings } from '../lib/types'

/** Global app settings: AI provider + frame extraction. Also offers a
 *  per-project "re-extract frames" action when opened inside a project. */
export default function SettingsPage({ pid }: { pid?: string }) {
  const [settings, setSettings] = useState<AppSettings | null>(null)
  const [status, setStatus] = useState('')
  const [testResult, setTestResult] = useState('')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setStatus(e.message))
  }, [])

  if (!settings) return <div className="empty-note">{status || 'Loading…'}</div>

  const set = (patch: Partial<AppSettings>) => {
    setSettings({ ...settings, ...patch })
    setDirty(true)
  }
  const setAI = (patch: Partial<AppSettings['ai']>) => set({ ai: { ...settings.ai, ...patch } })
  const setFrames = (patch: Partial<AppSettings['frames']>) =>
    set({ frames: { ...settings.frames, ...patch } })
  const setLyrics = (patch: Partial<AppSettings['lyrics']>) =>
    set({ lyrics: { ...settings.lyrics, ...patch } })
  const setFaces = (patch: Partial<AppSettings['faces']>) =>
    set({ faces: { ...settings.faces, ...patch } })
  const setAnalysis = (patch: Partial<AppSettings['analysis']>) =>
    set({ analysis: { ...settings.analysis, ...patch } })

  const save = async () => {
    setBusy(true)
    setStatus('')
    try {
      const saved = await api.saveSettings(settings)
      setSettings(saved)
      setDirty(false)
      setStatus('✓ Saved')
    } catch (e) {
      setStatus(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  const testAI = async () => {
    setBusy(true)
    setTestResult('testing…')
    try {
      await api.saveSettings(settings)
      setDirty(false)
      const r = await api.testAI()
      setTestResult(r.ok ? `✓ OK — provider: ${r.provider}` : `✗ ${r.error}`)
    } catch (e) {
      setTestResult(`✗ ${String((e as Error).message)}`)
    } finally {
      setBusy(false)
    }
  }

  const reextract = async () => {
    if (!pid) return
    setBusy(true)
    try {
      const r = await api.reextract(pid)
      setStatus(`✓ Re-extracting frames for ${r.queued} videos (see status bar)`)
    } catch (e) {
      setStatus(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  const clearAnalysis = async () => {
    if (!pid) return
    if (
      !window.confirm(
        'Delete the AI description, score and hashtags from EVERY video in this project?\n\nThis cannot be undone — the data is wiped and the clips go back to "extracted" (re-run analysis from the Library when you’re ready).',
      )
    )
      return
    setBusy(true)
    setStatus('')
    try {
      const r = await api.clearAnalysis(pid)
      setStatus(`✓ Cleared AI analysis from ${r.cleared} video(s)`)
    } catch (e) {
      setStatus(String((e as Error).message))
    } finally {
      setBusy(false)
    }
  }

  const num = (v: string, fallback: number) => {
    const n = Number(v)
    return Number.isFinite(n) ? n : fallback
  }

  const providerStatus = settings.ai_status
  const f = settings.frames
  const a = settings.ai
  const showAgy =
    a.provider === 'auto' || a.provider === 'agy' || settings.composer.provider === 'agy'
  const showOpenAI =
    a.provider === 'auto' || a.provider === 'openai' || settings.composer.provider === 'openai'

  return (
    <div className="setup-page">
      <div className="panel">
        <div className="panel-title-row">
          <h2>AI provider</h2>
          {providerStatus?.available ? (
            <span className="chip ok">active: {providerStatus.provider}</span>
          ) : (
            <span className="chip warn">none active</span>
          )}
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          Who analyzes the video frames (description, score, hashtags) and labels song sections.
        </p>
        <div className="settings-grid">
          <label>Provider</label>
          <select value={a.provider} onChange={(e) => setAI({ provider: e.target.value })}>
            <option value="auto">Auto (agy if installed, else OpenAI endpoint)</option>
            <option value="agy">Antigravity CLI (Gemini)</option>
            <option value="openai">OpenAI-compatible endpoint</option>
            <option value="off">Disabled</option>
          </select>

          <label>Composer provider (Montage)</label>
          <select
            value={settings.composer.provider}
            onChange={(e) => set({ composer: { provider: e.target.value } })}
          >
            <option value="mcp">Claude via MCP (external, as before)</option>
            <option value="agy">Antigravity CLI (Gemini) — one-shot prompt</option>
            <option value="openai">OpenAI-compatible endpoint — one-shot prompt</option>
          </select>

          {showAgy && (
            <>
              <label>Antigravity command</label>
              <input
                value={a.agy_cmd}
                onChange={(e) => setAI({ agy_cmd: e.target.value })}
                placeholder="agy --dangerously-skip-permissions -p"
              />
            </>
          )}

          {showOpenAI && (
            <>
              <label>OpenAI base URL</label>
              <input
                value={a.openai_base_url}
                onChange={(e) => setAI({ openai_base_url: e.target.value })}
                placeholder="https://api.z.ai/api/coding/paas/v4"
              />

              <label>API key</label>
              <input
                type="password"
                value={a.openai_api_key}
                onChange={(e) => setAI({ openai_api_key: e.target.value })}
                placeholder="sk-…"
                autoComplete="off"
              />

              <label>Model (vision-capable)</label>
              <input
                value={a.openai_model}
                onChange={(e) => setAI({ openai_model: e.target.value })}
                placeholder="glm-4.6v-flash"
              />
            </>
          )}

          <label>Timeout (s)</label>
          <input
            type="number"
            min={10}
            max={1800}
            value={a.timeout_s}
            onChange={(e) => setAI({ timeout_s: num(e.target.value, 300) })}
          />
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 12, alignItems: 'center' }}>
          <button onClick={testAI} disabled={busy}>Save & test AI</button>
          <span className="hint">{testResult}</span>
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          The <b>composer provider</b> powers the Auto-compose button on the Montage page: agy and
          the OpenAI endpoint reuse the credentials above and compose through a single prompt. With{' '}
          <b>Claude via MCP</b> the button is disabled — compose by talking to Claude with the MCP
          server registered, as before (see README).
        </p>
        <h3 style={{ marginTop: 16 }}>Clip analysis aspects</h3>
        <p className="hint">
          Besides the description, score and hashtags, the AI can extract these optional aspects
          from each clip. Disable an aspect if your provider handles it poorly — it stops being
          requested, shown and used by the composer (already stored values are kept and reappear
          if you re-enable it).
        </p>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.analysis.mood}
            onChange={(e) => setAnalysis({ mood: e.target.checked })}
          />
          <span><b>Mood</b> — emotional tone words (happy, calm, epic…)</span>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.analysis.energy}
            onChange={(e) => setAnalysis({ energy: e.target.checked })}
          />
          <span><b>Energy</b> — motion/action level (low/medium/high), matched to the music's intensity</span>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.analysis.scene}
            onChange={(e) => setAnalysis({ scene: e.target.checked })}
          />
          <span><b>Scene & context</b> — scene label, time of day and shot type</span>
        </label>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.analysis.people_in_prompt}
            onChange={(e) => setAnalysis({ people_in_prompt: e.target.checked })}
          />
          <span><b>People names in prompt</b> — if the clip has named people (People page), the description can use their names</span>
        </label>
        {showOpenAI && (
          <p className="hint" style={{ marginTop: 10 }}>
            For <b>z.ai GLM</b>, the base URL depends on your plan: API plan →{' '}
            <code>https://api.z.ai/api/paas/v4</code> (e.g. model <code>glm-4.6v-flash</code>);{' '}
            <b>Coding Plan</b> → <code>https://api.z.ai/api/coding/paas/v4</code> (e.g. model{' '}
            <code>glm-4.7</code> or <code>glm-4.6v</code> — these accept images too). A Coding Plan
            key only works on the coding endpoint. Any endpoint speaking the OpenAI{' '}
            <code>/chat/completions</code> protocol with image input works (OpenAI, OpenRouter,
            Ollama, LM Studio…). Frames are sent to that provider — use a local endpoint if you
            prefer to keep them on your machine.
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Frame extraction</h2>
        <p className="hint">
          How many frames are sampled from each video for the AI, and their size. More/larger
          frames = better analysis but slower and more tokens.
        </p>
        <div className="settings-grid">
          <label>Minimum frames per video</label>
          <input type="number" min={1} max={50} value={f.min_count}
            onChange={(e) => setFrames({ min_count: num(e.target.value, 3) })} />

          <label>Maximum frames per video</label>
          <input type="number" min={1} max={50} value={f.max_count}
            onChange={(e) => setFrames({ max_count: num(e.target.value, 10) })} />

          <label>+1 frame every N seconds</label>
          <input type="number" min={0.5} max={120} step={0.5} value={f.seconds_per_frame}
            onChange={(e) => setFrames({ seconds_per_frame: num(e.target.value, 5) })} />

          <label>Frame width (px)</label>
          <input type="number" min={160} max={1920} step={20} value={f.width}
            onChange={(e) => setFrames({ width: num(e.target.value, 640) })} />

          <label>JPEG quality (1 best – 10 worst)</label>
          <input type="number" min={1} max={10} value={f.jpeg_quality}
            onChange={(e) => setFrames({ jpeg_quality: num(e.target.value, 3) })} />

          <label>Filmstrip tiles (trim bar)</label>
          <input type="number" min={5} max={60} value={f.filmstrip_tiles}
            onChange={(e) => setFrames({ filmstrip_tiles: num(e.target.value, 20) })} />

          <label>Proxy height (px)</label>
          <input type="number" min={240} max={1080} step={120} value={f.proxy_height}
            onChange={(e) => setFrames({ proxy_height: num(e.target.value, 720) })} />

          <label>Preview height (px, montage SD mode)</label>
          <input type="number" min={144} max={720} step={36} value={f.preview_height}
            onChange={(e) => setFrames({ preview_height: num(e.target.value, 360) })} />
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          Example: min 3, max 10, +1 every 5 s → a 20 s clip gets 7 frames. Changes apply to
          videos scanned from now on{pid ? ' — or re-extract this project below' : ''}.
        </p>
      </div>

      <div className="panel">
        <h2>Music analysis — lyrics & vocals</h2>
        <p className="hint">
          Transcribes the song's lyrics and detects where the vocals are. The Music page then
          shows the timestamped lyrics and the melody-only (instrumental) passages, and the AI
          composer/labeler uses them to match footage to the song.
        </p>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.lyrics.enabled}
            onChange={(e) => setLyrics({ enabled: e.target.checked })}
          />
          <span>
            <b>Transcribe lyrics when analyzing the song</b>
            <br />
            <span className="hint">
              You can also run it on demand from the Music page.
            </span>
          </span>
        </label>
        <div className="settings-grid" style={{ marginTop: 10 }}>
          <label>Engine</label>
          <select
            value={settings.lyrics.provider}
            onChange={(e) => setLyrics({ provider: e.target.value })}
          >
            <option value="auto">Auto — local Whisper if installed, else agy</option>
            <option value="whisper">Whisper (local) — private, precise timestamps</option>
            <option value="agy">Antigravity CLI (Gemini) — no local model needed</option>
          </select>

          <label>Whisper model</label>
          <select
            value={settings.lyrics.whisper_model}
            disabled={settings.lyrics.provider === 'agy'}
            onChange={(e) => setLyrics({ whisper_model: e.target.value })}
          >
            <option value="tiny">tiny — fastest, rough</option>
            <option value="base">base</option>
            <option value="small">small — good default</option>
            <option value="medium">medium</option>
            <option value="large-v3">large-v3 — best, slow</option>
          </select>

          <label>Language (ISO code, empty = auto)</label>
          <input
            value={settings.lyrics.language}
            onChange={(e) => setLyrics({ language: e.target.value })}
            placeholder="auto (or es, en, fr…)"
          />

          <label>Min. instrumental gap (s)</label>
          <input
            type="number"
            min={2}
            max={60}
            value={settings.lyrics.min_instrumental_gap}
            onChange={(e) => setLyrics({ min_instrumental_gap: num(e.target.value, 5) })}
          />
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          A stretch without vocals at least this long is marked as an instrumental
          (melody-only) part — useful spots for scenic footage.
        </p>
        <p className="hint">
          Whisper runs fully on this machine (requires <code>pip install faster-whisper</code>;
          the first run downloads the model). The Antigravity CLI engine uploads the song's
          audio to Google and returns approximate (~1s) timestamps, but needs no local model.
        </p>
      </div>

      <div className="panel">
        <h2>People detection (faces)</h2>
        <p className="hint">
          Finds the people appearing in each clip (People page). Runs fully on this machine;
          requires <code>pip install insightface onnxruntime opencv-python-headless</code> in the
          backend environment. The first detection downloads the face model.
        </p>
        <div className="settings-grid">
          <label>Model pack</label>
          <select
            value={settings.faces.model_pack}
            onChange={(e) => setFaces({ model_pack: e.target.value })}
          >
            <option value="buffalo_l">buffalo_l — most accurate (~280 MB)</option>
            <option value="buffalo_s">buffalo_s — faster on weak CPUs (~30 MB)</option>
          </select>

          <label>Sample one frame every N seconds</label>
          <input type="number" min={0.5} max={30} step={0.5} value={settings.faces.frame_interval_s}
            onChange={(e) => setFaces({ frame_interval_s: num(e.target.value, 2) })} />

          <label>Max frames per video</label>
          <input type="number" min={5} max={200} value={settings.faces.max_frames}
            onChange={(e) => setFaces({ max_frames: num(e.target.value, 40) })} />
        </div>
        <p className="hint" style={{ marginTop: 10 }}>
          Denser sampling (lower interval, more frames) catches people who appear briefly, at the
          cost of slower detection. Changes apply to detections run from now on.
        </p>
      </div>

      <div className="panel">
        <h2>Logging</h2>
        <p className="hint">
          Controls how much the backend records in the <b>Logs</b> tab.
        </p>
        <label className="toggle-row">
          <input
            type="checkbox"
            checked={settings.debug_logging}
            onChange={(e) => set({ debug_logging: e.target.checked })}
          />
          <span>
            <b>Verbose (debug) logging</b>
            <br />
            <span className="hint">
              Also captures the full AI prompts and raw model responses — useful to debug why a
              clip's analysis failed. Applies as soon as you save (no restart needed). The{' '}
              <code>MONTAGE_LOG_LEVEL</code> env var, if set, overrides this.
            </span>
          </span>
        </label>
      </div>

      {pid && (
        <div className="panel">
          <h2>This project</h2>
          <p className="hint">
            Maintenance actions that only affect the project you have open — global settings above
            are not touched.
          </p>
          <div className="project-actions">
            <div className="project-action">
              <div>
                <b>Re-extract frames</b>
                <p className="hint">
                  Regenerates frames, thumbnails and filmstrips with the extraction settings above.
                  Runs in the background; originals are untouched.
                </p>
              </div>
              <button onClick={reextract} disabled={busy}>Re-extract</button>
            </div>
            <div className="project-action danger-zone">
              <div>
                <b>Clear AI analysis</b>
                <p className="hint">
                  Wipes the AI description, score and hashtags from every clip (frames are kept;
                  clips go back to "extracted"). Cannot be undone.
                </p>
              </div>
              <button className="danger" onClick={clearAnalysis} disabled={busy}>Clear…</button>
            </div>
          </div>
        </div>
      )}

      <div className="save-bar">
        <button className="primary" onClick={save} disabled={busy}>Save settings</button>
        {dirty && <span className="chip warn">unsaved changes</span>}
        <span className="hint">{status}</span>
      </div>
    </div>
  )
}
