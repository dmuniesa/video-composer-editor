import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import type { ProjectInfo } from '../lib/types'
import FileBrowser from '../components/FileBrowser'

interface Props {
  project: ProjectInfo | null
  onChanged: () => void
  standalone?: boolean
}

export default function SetupPage({ project, onChanged, standalone }: Props) {
  const navigate = useNavigate()
  const [recent, setRecent] = useState<{ id: string; video_dir: string; name: string }[]>([])
  const [pickingSong, setPickingSong] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (standalone) api.listProjects().then(setRecent).catch(() => {})
  }, [standalone])

  const openDir = async (dir: string) => {
    try {
      const p = await api.createProject(dir)
      await api.scan(p.id)
      navigate(`/p/${p.id}/setup`)
    } catch (e) {
      setError(String((e as Error).message))
    }
  }

  if (standalone || !project) {
    return (
      <div className="setup-page">
        <div className="panel">
          <h2>🎬 Video Montage Composer</h2>
          <p className="hint">
            Pick the folder that contains your trip videos. The app scans it, extracts frames,
            and (with the Antigravity CLI installed) asks Gemini to describe and score every clip.
          </p>
          {recent.length > 0 && (
            <div style={{ marginBottom: 14 }}>
              <h2>Recent projects</h2>
              {recent.map((r) => (
                <button key={r.id} style={{ marginRight: 8, marginBottom: 8 }} onClick={() => navigate(`/p/${r.id}/setup`)}>
                  {r.name} <span className="hint">{r.video_dir}</span>
                </button>
              ))}
            </div>
          )}
          <FileBrowser mode="dir" onPick={openDir} />
          {error && <div className="error-text">{error}</div>}
        </div>
      </div>
    )
  }

  const byStatus = project.videos_by_status
  return (
    <div className="setup-page">
      <div className="panel">
        <h2>Project: {project.name}</h2>
        <div className="crumb">{project.video_dir}</div>
        <div className="stat-row">
          <span><b>{project.video_count}</b> videos</span>
          <span>pending <b>{byStatus['pending'] ?? 0}</b></span>
          <span>extracting <b>{byStatus['extracting'] ?? 0}</b></span>
          <span>extracted <b>{byStatus['extracted'] ?? 0}</b></span>
          <span>analyzing <b>{byStatus['analyzing'] ?? 0}</b></span>
          <span>ready <b>{byStatus['ready'] ?? 0}</b></span>
          <span style={{ color: 'var(--danger)' }}>errors <b>{byStatus['error'] ?? 0}</b></span>
        </div>
        <div style={{ display: 'flex', gap: 8, marginTop: 14 }}>
          <button onClick={() => api.scan(project.id).then(onChanged).catch((e) => setError(e.message))}>
            Rescan folder
          </button>
          <button
            className="primary"
            disabled={!project.ai_available}
            title={project.ai_available ? `provider: ${project.ai_provider}` : 'No AI provider configured'}
            onClick={() => api.analyze(project.id).then(onChanged).catch((e) => setError(e.message))}
          >
            Analyze all with AI{project.ai_provider ? ` (${project.ai_provider})` : ''}
          </button>
        </div>
        {!project.ai_available && (
          <p className="hint" style={{ marginTop: 10 }}>
            ⚠️ No AI provider available — AI analysis is disabled. Install the Antigravity CLI
            (<code>agy</code>) and sign in, or configure an OpenAI-compatible endpoint (e.g. z.ai
            GLM) on the <b>Settings</b> page. Rating and manual tagging still work.
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Song</h2>
        {project.song_path ? (
          <div className="stat-row" style={{ marginBottom: 10 }}>
            <span className="crumb">{project.song_path}</span>
            <span>status: <b>{project.song_status}</b></span>
          </div>
        ) : (
          <p className="hint">No song selected yet. Pick the track for your montage.</p>
        )}
        {pickingSong ? (
          <FileBrowser
            mode="audio"
            initialPath={project.video_dir}
            onPick={(path) => {
              setPickingSong(false)
              api.setSong(project.id, path).then(onChanged).catch((e) => setError(e.message))
            }}
          />
        ) : (
          <button onClick={() => setPickingSong(true)}>
            {project.song_path ? 'Change song' : 'Choose song…'}
          </button>
        )}
      </div>
      {error && <div className="error-text">{error}</div>}
    </div>
  )
}
