import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import FileBrowser from '../components/FileBrowser'

const STEPS = [
  {
    icon: '📁',
    title: 'Scan',
    text: 'Add one or more folders of videos. Frames, thumbnails and proxies are extracted automatically.',
  },
  {
    icon: '✨',
    title: 'Analyze',
    text: 'AI describes, scores and tags every clip — Gemini or any OpenAI-compatible endpoint.',
  },
  {
    icon: '⭐',
    title: 'Review',
    text: 'Cull Lightroom-style: rate, reject, and mark the best moments of each clip.',
  },
  {
    icon: '🎵',
    title: 'Music',
    text: 'Your song is analyzed locally: BPM, beats and structure sections to cut against.',
  },
  {
    icon: '🎞️',
    title: 'Montage',
    text: 'Drag clips onto a multi-track timeline with beat snapping — or let AI place them.',
  },
  {
    icon: '📤',
    title: 'Export',
    text: 'One click gives you a ready sequence for Premiere Pro, DaVinci Resolve or Final Cut Pro.',
  },
]

export default function HomePage() {
  const navigate = useNavigate()
  const [recent, setRecent] = useState<{ id: string; video_dir: string; name: string }[]>([])
  const [browsing, setBrowsing] = useState<null | 'new' | 'import'>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.listProjects().then(setRecent).catch(() => {})
  }, [])

  const importDir = async (dir: string) => {
    try {
      const p = await api.importProject(dir)
      navigate(`/p/${p.id}/setup`)
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  // Import opens the native OS folder dialog directly; fall back to the in-app
  // browser panel when no native dialog is available (headless Linux w/o Tk).
  const chooseImport = async () => {
    setError('')
    try {
      const r = await api.pickPath('dir')
      if (!r.ok) {
        setBrowsing('import')
        return
      }
      if (r.path) importDir(r.path)
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  return (
    <div className="home-page">
      <nav className="home-nav">
        <span className="brand">
          <img src="/favicon.svg" alt="" className="brand-icon" />
          Beatcut
        </span>
        <span className="spacer" />
        <Link to="/guide">Guide</Link>
        <Link to="/settings">Settings</Link>
      </nav>

      <header className="home-hero">
        <img src="/favicon.svg" alt="Beatcut" className="hero-logo" />
        <div className="hero-badge">Runs 100% on your machine</div>
        <h1>
          From a folder of clips to a<br />
          <span className="grad">Premiere-ready montage</span>
        </h1>
        <p className="hero-sub">
          Scan your footage, let AI rate and describe every clip, cut them to the beat of your
          song on a real timeline, and export straight to Premiere Pro, DaVinci Resolve or Final
          Cut Pro.
        </p>
        <div className="hero-actions">
          {!browsing && (
            <>
              <button className="primary big" onClick={() => navigate('/new')}>
                ＋ New project
              </button>
              <button className="big" onClick={chooseImport}>
                Import project
              </button>
            </>
          )}
          <Link to="/guide" className="ghost-link">
            Read the guide →
          </Link>
        </div>
      </header>

      <div className="home-body">
        {browsing === 'import' && (
          <section className="panel">
            <div className="panel-title-row">
              <h2>Import an existing project</h2>
              <button className="small" onClick={() => setBrowsing(null)}>
                Cancel
              </button>
            </div>
            <p className="hint" style={{ marginTop: 0 }}>
              Pick the project's storage folder — the one that contains its{' '}
              <code>.montage-cache/</code> subfolder. It is re-registered here with all its clips,
              ratings and timeline intact.
            </p>
            <FileBrowser mode="dir" onPick={importDir} />
            {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
          </section>
        )}

        {recent.length > 0 && (
          <section>
            <h2 className="section-title">Recent projects</h2>
            <div className="project-grid">
              {recent.map((r) => (
                <button key={r.id} className="project-card" onClick={() => navigate(`/p/${r.id}/setup`)}>
                  <span className="project-icon">🎬</span>
                  <span className="project-meta">
                    <span className="project-name">{r.name}</span>
                    <span className="project-path">{r.video_dir}</span>
                  </span>
                  <span className="project-open">Open →</span>
                </button>
              ))}
            </div>
          </section>
        )}

        <section>
          <h2 className="section-title">How it works</h2>
          <div className="steps-grid">
            {STEPS.map((s, i) => (
              <div key={s.title} className="step-card">
                <div className="step-head">
                  <span className="step-icon">{s.icon}</span>
                  <span className="step-num">{i + 1}</span>
                </div>
                <h3>{s.title}</h3>
                <p>{s.text}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <footer className="home-footer">
        <span>
          Autosaves everything, instantly — each project lives in its own folder and travels with
          it.
        </span>
        <span className="dot">·</span>
        <Link to="/guide">User guide</Link>
        <span className="dot">·</span>
        <a href="https://github.com/dmuniesa/video-composer-editor" target="_blank" rel="noreferrer">
          GitHub
        </a>
      </footer>
    </div>
  )
}
