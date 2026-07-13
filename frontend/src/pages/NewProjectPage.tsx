import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import FileBrowser from '../components/FileBrowser'

function basename(p: string) {
  return p.split(/[\\/]/).pop() ?? p
}

export default function NewProjectPage() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [dir, setDir] = useState('')
  const [browsing, setBrowsing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  // Native OS folder dialog first; fall back to the in-app browser when no
  // native dialog is available (headless Linux without python3-tk).
  const chooseFolder = async () => {
    setError('')
    try {
      const r = await api.pickPath('dir')
      if (!r.ok) return setBrowsing(true)
      if (r.path) {
        setDir(r.path)
        setBrowsing(false)
      }
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  const create = async () => {
    if (!dir) return
    setCreating(true)
    setError('')
    try {
      const p = await api.createProject(dir, name.trim())
      navigate(`/p/${p.id}/setup`)
    } catch (e) {
      setError(String((e as Error).message))
      setCreating(false)
    }
  }

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

      <main className="app-main">
        <div className="setup-page">
          <header className="setup-header">
            <div className="setup-title">
              <h1 className="name-title">New project</h1>
              <div className="crumb" style={{ marginBottom: 0 }}>
                Choose where to save the project — you'll add your footage folders next.
              </div>
            </div>
          </header>

          <div className="panel">
            <div className="panel-title-row">
              <h2>Storage folder</h2>
              {dir && <span className="chip ok">selected</span>}
            </div>
            <p className="hint" style={{ marginTop: 0 }}>
              Where the project's database and everything the app generates live (a{' '}
              <code>.montage-cache/</code> subfolder). It is <b>separate from your footage</b> and
              can be an empty folder — your original videos are added as source folders afterwards
              and never touched.
            </p>
            {dir && (
              <div className="crumb" style={{ marginBottom: 8 }} title="Project storage folder">
                📦 {dir}
              </div>
            )}
            {browsing ? (
              <div className="panel-inset">
                <div className="panel-title-row">
                  <h3 style={{ margin: 0 }}>Pick a storage folder</h3>
                  <button className="small" onClick={() => setBrowsing(false)}>Cancel</button>
                </div>
                <FileBrowser
                  mode="dir"
                  onPick={(path) => {
                    setDir(path)
                    setBrowsing(false)
                  }}
                />
              </div>
            ) : (
              <button className="primary" onClick={chooseFolder}>
                {dir ? 'Change folder…' : 'Choose folder…'}
              </button>
            )}
          </div>

          <div className="panel">
            <h2>Name</h2>
            <p className="hint" style={{ marginTop: 0 }}>Optional — defaults to the folder name. You can rename it anytime.</p>
            <input
              className="name-edit"
              value={name}
              maxLength={200}
              placeholder={dir ? basename(dir) : 'My montage'}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && dir) create()
              }}
            />
          </div>

          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="primary" disabled={!dir || creating} onClick={create}>
              {creating ? 'Creating…' : 'Create project →'}
            </button>
            <Link to="/">Cancel</Link>
          </div>

          {error && <div className="error-text" style={{ marginTop: 8 }}>{error}</div>}
        </div>
      </main>
    </div>
  )
}
