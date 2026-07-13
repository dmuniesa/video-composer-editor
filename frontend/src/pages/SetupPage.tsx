import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtTime } from '../lib/api'
import type { ProjectInfo, SongInfo } from '../lib/types'
import FileBrowser from '../components/FileBrowser'

interface Props {
  project: ProjectInfo | null
  onChanged: () => void
}

const PIPELINE: { key: string; label: string; color: string }[] = [
  { key: 'ready', label: 'ready', color: 'var(--ok)' },
  { key: 'analyzing', label: 'analyzing', color: '#9b6fd0' },
  { key: 'extracted', label: 'extracted', color: 'var(--accent)' },
  { key: 'extracting', label: 'extracting', color: 'rgba(79, 140, 255, 0.45)' },
  { key: 'pending', label: 'pending', color: 'var(--border)' },
  { key: 'error', label: 'errors', color: 'var(--danger)' },
]

function basename(p: string) {
  return p.split(/[\\/]/).pop() ?? p
}

export default function SetupPage({ project, onChanged }: Props) {
  const [pickingSong, setPickingSong] = useState(false)
  const [error, setError] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [song, setSong] = useState<SongInfo | null>(null)
  const [reviewed, setReviewed] = useState<{ rated: number; total: number } | null>(null)
  const [placedClips, setPlacedClips] = useState<number | null>(null)

  const pid = project?.id
  const songStatus = project?.song_status

  useEffect(() => {
    if (!pid) return
    if (songStatus) api.song(pid).then(setSong).catch(() => setSong(null))
    else setSong(null)
  }, [pid, songStatus])

  useEffect(() => {
    if (!pid) return
    api
      .videos(pid)
      .then((vs) => setReviewed({ rated: vs.filter((v) => v.stars > 0 || v.rejected).length, total: vs.length }))
      .catch(() => {})
    api
      .timeline(pid)
      .then((t) => setPlacedClips(t.tracks.reduce((n, tr) => n + tr.clips.length, 0)))
      .catch(() => {})
  }, [pid, project])

  if (!project) {
    return <div className="empty-note">loading project…</div>
  }

  const startEditName = () => {
    setNameDraft(project.name)
    setEditingName(true)
    setError('')
  }

  const saveName = () => {
    const name = nameDraft.trim()
    setEditingName(false)
    if (!name || name === project.name) return
    api
      .updateProject(project.id, { name })
      .then(onChanged)
      .catch((e) => setError(e.message))
  }

  const byStatus = project.videos_by_status
  const count = (k: string) => byStatus[k] ?? 0
  const total = project.video_count
  const ready = count('ready')
  const working = count('extracting') + count('analyzing') + count('pending') + count('extracted')

  const steps: { label: string; detail: string; done: boolean; to?: string }[] = [
    {
      label: 'Scan your folder',
      detail: total > 0 ? `${total} videos found` : 'no videos found yet — check the folder and rescan',
      done: total > 0,
    },
    {
      label: 'Analyze clips with AI',
      detail: project.ai_available
        ? total > 0 && ready === total
          ? 'every clip has a description and score'
          : `${ready} of ${total} clips ready${working > 0 ? ' — analysis in progress' : ''}`
        : 'optional — configure a provider in Settings',
      done: total > 0 && ready === total,
    },
    {
      label: 'Pick a song',
      detail: project.song_path
        ? `${basename(project.song_path)} (${project.song_status})`
        : 'the montage is cut to its beats and sections',
      done: !!project.song_path,
    },
    {
      label: 'Review & rate your clips',
      detail: reviewed && reviewed.rated > 0 ? `${reviewed.rated} of ${reviewed.total} clips rated or rejected` : 'cull the junk, star the keepers',
      done: !!reviewed && reviewed.rated > 0,
      to: `/p/${project.id}/review`,
    },
    {
      label: 'Build the montage & export',
      detail:
        placedClips && placedClips > 0
          ? `${placedClips} clips on the timeline`
          : 'drag clips onto the timeline — or let AI place them',
      done: !!placedClips && placedClips > 0,
      to: `/p/${project.id}/montage`,
    },
  ]

  return (
    <div className="setup-page">
      <header className="setup-header">
        <div className="setup-title">
          {editingName ? (
            <input
              className="name-edit"
              autoFocus
              value={nameDraft}
              maxLength={200}
              onChange={(e) => setNameDraft(e.target.value)}
              onBlur={saveName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') saveName()
                else if (e.key === 'Escape') setEditingName(false)
              }}
            />
          ) : (
            <h1 className="name-title" onClick={startEditName} title="Click to rename">
              {project.name}
              <span className="name-edit-icon" aria-hidden>✎</span>
            </h1>
          )}
          <div className="crumb" style={{ marginBottom: 0 }}>{project.video_dir}</div>
        </div>
        <button onClick={() => api.scan(project.id).then(onChanged).catch((e) => setError(e.message))}>
          ⟳ Rescan folder
        </button>
      </header>

      <div className="panel">
        <div className="panel-title-row">
          <h2>Clips</h2>
          <span className="hint">
            {total > 0 && ready === total ? '✓ all processed' : working > 0 ? 'processing…' : ''}
          </span>
        </div>
        {total === 0 ? (
          <p className="hint" style={{ margin: 0 }}>
            No videos in this folder yet. Add your footage and hit <b>Rescan folder</b>.
          </p>
        ) : (
          <>
            <div className="clip-summary">
              <span className="big-num">{ready}</span>
              <span className="hint">of {total} clips analyzed and ready</span>
            </div>
            <div className="seg-bar" role="img" aria-label="clip processing progress">
              {PIPELINE.filter((s) => count(s.key) > 0).map((s) => (
                <div
                  key={s.key}
                  title={`${s.label}: ${count(s.key)}`}
                  style={{ flex: count(s.key), background: s.color }}
                />
              ))}
            </div>
            <div className="legend">
              {PIPELINE.filter((s) => count(s.key) > 0 || s.key === 'ready').map((s) => (
                <span key={s.key} className="legend-item">
                  <span className="dot" style={{ background: s.color }} />
                  {s.label} <b>{count(s.key)}</b>
                </span>
              ))}
            </div>
            {count('error') > 0 && (
              <p className="hint" style={{ color: 'var(--danger)', marginBottom: 0 }}>
                {count('error')} clip{count('error') > 1 ? 's' : ''} failed — hover the card on the{' '}
                <Link to={`/p/${project.id}/review`}>Review</Link> page to read the error, then rescan.
              </p>
            )}
          </>
        )}
      </div>

      <div className="panel">
        <div className="panel-title-row">
          <h2>AI analysis</h2>
          {project.ai_available ? (
            <span className="chip ok">provider: {project.ai_provider}</span>
          ) : (
            <span className="chip warn">not configured</span>
          )}
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          The AI writes a description, a 1–10 score and hashtags for every clip — the raw material
          for sorting on the Review page and for AI auto-placement.
        </p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className="primary"
            disabled={!project.ai_available}
            title={project.ai_available ? `provider: ${project.ai_provider}` : 'No AI provider configured'}
            onClick={() => api.analyze(project.id).then(onChanged).catch((e) => setError(e.message))}
          >
            Analyze all with AI{project.ai_provider ? ` (${project.ai_provider})` : ''}
          </button>
          {!project.ai_available && (
            <Link to={`/p/${project.id}/settings`}>Configure a provider in Settings →</Link>
          )}
        </div>
        {!project.ai_available && (
          <p className="hint" style={{ marginBottom: 0 }}>
            Install the Antigravity CLI (<code>agy</code>) and sign in, or configure an
            OpenAI-compatible endpoint (z.ai GLM, OpenAI, Ollama…). Rating and manual tagging work
            without it.
          </p>
        )}
      </div>

      <div className="panel">
        <div className="panel-title-row">
          <h2>Song</h2>
          {project.song_path && (
            <span className={`chip ${project.song_status === 'ready' ? 'ok' : project.song_status === 'error' ? 'danger' : ''}`}>
              {project.song_status}
            </span>
          )}
        </div>
        {project.song_path ? (
          <div className="song-card">
            <span className="song-icon">🎵</span>
            <div className="song-meta">
              <div className="song-name">{basename(project.song_path)}</div>
              <div className="hint">
                {song && song.status === 'ready' ? (
                  <>
                    {fmtTime(song.duration)} · {song.bpm ? `${Math.round(song.bpm)} BPM` : 'BPM —'} ·{' '}
                    {song.sections.length} sections · <Link to={`/p/${project.id}/music`}>open Music →</Link>
                  </>
                ) : (
                  <span className="crumb" style={{ marginBottom: 0 }}>{project.song_path}</span>
                )}
              </div>
            </div>
          </div>
        ) : (
          <p className="hint" style={{ marginTop: 0 }}>
            No song selected yet. Pick the track for your montage — it is analyzed locally (BPM,
            beats, structure sections) and everything on the timeline snaps to it.
          </p>
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

      <div className="panel">
        <h2>Next steps</h2>
        <ol className="steps-list">
          {steps.map((s) => (
            <li key={s.label} className={s.done ? 'done' : ''}>
              <span className="step-check">{s.done ? '✓' : '○'}</span>
              <span className="step-body">
                <span className="step-label">{s.to ? <Link to={s.to}>{s.label}</Link> : s.label}</span>
                <span className="hint">{s.detail}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>

      {error && <div className="error-text">{error}</div>}
    </div>
  )
}
