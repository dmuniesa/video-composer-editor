import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtTime } from '../lib/api'
import type { ProjectInfo, SongInfo, Source, Video } from '../lib/types'
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
  const [addingSource, setAddingSource] = useState(false)
  const [relinking, setRelinking] = useState<Source | null>(null)
  const [error, setError] = useState('')
  const [editingName, setEditingName] = useState(false)
  const [nameDraft, setNameDraft] = useState('')
  const [song, setSong] = useState<SongInfo | null>(null)
  const [videos, setVideos] = useState<Video[]>([])
  const [placedClips, setPlacedClips] = useState<number | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [picked, setPicked] = useState<Set<number>>(new Set())

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
      .then((vs) => setVideos([...vs].sort((a, b) => a.filename.localeCompare(b.filename))))
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

  const addSource = (path: string) => {
    setAddingSource(false)
    setError('')
    api.addSource(project.id, path).then(onChanged).catch((e) => setError(e.message))
  }

  const relink = (path: string) => {
    const s = relinking
    setRelinking(null)
    if (!s) return
    api.updateSource(project.id, s.id, { path }).then(onChanged).catch((e) => setError(e.message))
  }

  const removeSource = (s: Source) => {
    if (!window.confirm(`Remove "${s.label}" and its ${s.video_count} clip(s) from this project? The original files are not deleted.`)) return
    api.removeSource(project.id, s.id).then(onChanged).catch((e) => setError(e.message))
  }

  // Native OS dialogs first; fall back to the in-app browser panels when no
  // native dialog is available (headless Linux without python3-tk).
  const chooseAddFolder = async () => {
    setError('')
    try {
      const r = await api.pickPath('dir')
      if (!r.ok) return setAddingSource(true)
      if (r.path) addSource(r.path)
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const chooseRelink = async (s: Source) => {
    setError('')
    try {
      const r = await api.pickPath('dir', s.online ? s.path : '')
      if (!r.ok) return setRelinking(s)
      if (r.path) api.updateSource(project.id, s.id, { path: r.path }).then(onChanged).catch((e) => setError(e.message))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const chooseSong = async () => {
    setError('')
    try {
      const r = await api.pickPath('audio', project.sources[0]?.path ?? project.video_dir)
      if (!r.ok) return setPickingSong(true)
      if (r.path) api.setSong(project.id, r.path).then(onChanged).catch((e) => setError(e.message))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const byStatus = project.videos_by_status
  const count = (k: string) => byStatus[k] ?? 0
  const total = project.video_count
  const ready = count('ready')
  const working = count('extracting') + count('analyzing') + count('pending') + count('extracted')
  const reviewedCount = videos.filter((v) => v.stars > 0 || v.rejected).length

  const togglePicked = (id: number) =>
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const analyze = (ids?: number[]) => {
    setError('')
    api
      .analyze(project.id, ids)
      .then(() => {
        setPicked(new Set())
        return onChanged()
      })
      .catch((e) => setError(e.message))
  }

  const steps: { label: string; detail: string; done: boolean; to?: string }[] = [
    {
      label: 'Add your footage folders',
      detail:
        total > 0
          ? `${total} videos across ${project.sources.length} folder${project.sources.length === 1 ? '' : 's'}`
          : project.sources.length === 0
            ? 'add one or more folders of footage above'
            : 'no videos found yet — check the folders and rescan',
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
      detail: reviewedCount > 0 ? `${reviewedCount} of ${videos.length} clips rated or rejected` : 'cull the junk, star the keepers',
      done: reviewedCount > 0,
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
          <div className="crumb" style={{ marginBottom: 0 }} title="Project storage folder">
            📦 {project.video_dir}
          </div>
        </div>
        <button onClick={() => api.scan(project.id).then(onChanged).catch((e) => setError(e.message))}>
          ⟳ Rescan all
        </button>
      </header>

      <div className="panel">
        <div className="panel-title-row">
          <h2>Source folders</h2>
          <span className="hint">{project.sources.length} folder{project.sources.length === 1 ? '' : 's'}</span>
        </div>
        <p className="hint" style={{ marginTop: 0 }}>
          The folders scanned for footage. Add or remove them anytime, or repoint one that moved —
          each clip keeps its analysis, ratings and timeline placement.
        </p>
        {project.sources.length > 0 && (
          <ul className="source-list">
            {project.sources.map((s) => (
              <li key={s.id} className="source-row">
                <span className="source-icon" aria-hidden>{s.online ? '📁' : '⚠️'}</span>
                <span className="source-meta">
                  <span className="source-label">{s.label}</span>
                  <span className="crumb" style={{ marginBottom: 0 }}>{s.path}</span>
                  {!s.online && (
                    <span className="hint" style={{ color: 'var(--danger)' }}>
                      folder not found — use “Repoint” to relink it
                    </span>
                  )}
                </span>
                <span className="source-count hint">{s.video_count} clip{s.video_count === 1 ? '' : 's'}</span>
                <button className="small" onClick={() => { setAddingSource(false); chooseRelink(s) }}>
                  Repoint…
                </button>
                <button className="small danger" title="Remove folder" onClick={() => removeSource(s)}>
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
        {relinking ? (
          <div className="panel-inset">
            <div className="panel-title-row">
              <h3 style={{ margin: 0 }}>New location for “{relinking.label}”</h3>
              <button className="small" onClick={() => setRelinking(null)}>Cancel</button>
            </div>
            <FileBrowser mode="dir" initialPath={relinking.online ? relinking.path : undefined} onPick={relink} />
          </div>
        ) : addingSource ? (
          <div className="panel-inset">
            <div className="panel-title-row">
              <h3 style={{ margin: 0 }}>Pick a footage folder</h3>
              <button className="small" onClick={() => setAddingSource(false)}>Cancel</button>
            </div>
            <FileBrowser mode="dir" onPick={addSource} />
          </div>
        ) : (
          <button className="primary" onClick={chooseAddFolder}>＋ Add folder</button>
        )}
      </div>

      <div className="panel">
        <div className="panel-title-row">
          <h2>Clips</h2>
          <span className="hint">
            {total > 0 && ready === total ? '✓ all processed' : working > 0 ? 'processing…' : ''}
          </span>
        </div>
        {total === 0 ? (
          <p className="hint" style={{ margin: 0 }}>
            {project.sources.length === 0 ? (
              <>No footage yet. Add a <b>source folder</b> above to get started.</>
            ) : (
              <>No videos in these folders yet. Add your footage and hit <b>Rescan all</b>.</>
            )}
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
          The AI writes a description, a 1–10 score and hashtags for every clip — plus mood,
          energy and scene context (toggle each in Settings) — the raw material
          for sorting on the Review page and for AI auto-placement. It runs only when you ask:
          analyze every not-yet-analyzed clip, or expand the list to pick just the ones you want.
        </p>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <button
            className="primary"
            disabled={!project.ai_available}
            title={project.ai_available ? `provider: ${project.ai_provider}` : 'No AI provider configured'}
            onClick={() => analyze()}
          >
            Analyze all with AI{project.ai_provider ? ` (${project.ai_provider})` : ''}
          </button>
          {!project.ai_available && (
            <Link to={`/p/${project.id}/settings`}>Configure a provider in Settings →</Link>
          )}
        </div>

        {project.ai_available && total > 0 && (
          <div className="pick-block">
            <button
              className="pick-toggle"
              aria-expanded={pickerOpen}
              onClick={() => setPickerOpen((o) => !o)}
            >
              <span className="pick-caret" aria-hidden>{pickerOpen ? '▾' : '▸'}</span>
              Choose specific clips to analyze
              <span className="hint">
                — {picked.size > 0 ? `${picked.size} selected` : `${total} clip${total === 1 ? '' : 's'}`}
              </span>
            </button>
            {pickerOpen && (
              <div className="pick-panel">
                <div className="pick-actions">
                  <button className="small" onClick={() => setPicked(new Set(videos.map((v) => v.id)))}>All</button>
                  <button className="small" onClick={() => setPicked(new Set())}>None</button>
                  <button
                    className="small"
                    title="Select every clip that has no AI description yet"
                    onClick={() => setPicked(new Set(videos.filter((v) => v.status !== 'ready').map((v) => v.id)))}
                  >
                    Un-analyzed
                  </button>
                  <span className="pick-spacer" />
                  <button className="primary small" disabled={picked.size === 0} onClick={() => analyze([...picked])}>
                    Analyze {picked.size || ''} selected
                  </button>
                </div>
                <ul className="pick-list">
                  {videos.map((v) => (
                    <li key={v.id}>
                      <label>
                        <input type="checkbox" checked={picked.has(v.id)} onChange={() => togglePicked(v.id)} />
                        <span className="pick-name" title={v.rel_path}>{v.filename}</span>
                        {v.status === 'ready' ? (
                          <span className="chip ok">{v.ai_score != null ? `AI ${v.ai_score}/10` : 'analyzed'}</span>
                        ) : v.status === 'analyzing' ? (
                          <span className="chip">analyzing…</span>
                        ) : v.status === 'error' ? (
                          <span className="chip danger">error</span>
                        ) : (
                          <span className="chip">not analyzed</span>
                        )}
                      </label>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

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
            initialPath={project.sources[0]?.path ?? project.video_dir}
            onPick={(path) => {
              setPickingSong(false)
              api.setSong(project.id, path).then(onChanged).catch((e) => setError(e.message))
            }}
          />
        ) : (
          <button onClick={chooseSong}>
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
