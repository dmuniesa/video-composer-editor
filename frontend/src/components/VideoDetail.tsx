import { useCallback, useEffect, useRef, useState } from 'react'
import { api, media, fmtTime, fmtBytes } from '../lib/api'
import type { Video, VideoRange } from '../lib/types'
import StarRating from './StarRating'
import {
  IcBan, IcBolt, IcCamera, IcClose, IcLoop, IcPin, IcPlay, IcPlus, IcSmile, IcSparkles, IcTrash,
} from './icons'

interface Props {
  pid: string
  video: Video
  aiAvailable?: boolean
  /** Seek here on open (deep links, e.g. a face clicked on the People page). */
  initialTime?: number
  onClose: () => void
  onChanged: () => void
  onRate: (stars: number) => void
  onReject: (rejected: boolean) => void
  onDelete: () => void
}

/** Detail drawer: player + trim bar with in/out handles over a filmstrip.
 *  Keyboard: I = set in, O = set out, Enter = save range, L = loop range.
 *  The hint line shows the common keys; the full list is behind the ? toggle. */
export default function VideoDetail({ pid, video, aiAvailable, initialTime, onClose, onChanged, onRate, onReject, onDelete }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const [playhead, setPlayhead] = useState(0)
  const [draftIn, setDraftIn] = useState<number | null>(null)
  const [draftOut, setDraftOut] = useState<number | null>(null)
  const [activeRange, setActiveRange] = useState<VideoRange | null>(null)
  // null = free playback; 'once' plays the active range then pauses at its out
  // point; 'loop' repeats it until stopped.
  const [playMode, setPlayMode] = useState<'once' | 'loop' | null>(null)
  const [editTags, setEditTags] = useState(false)
  const [tagsText, setTagsText] = useState(video.hashtags.join(' '))
  const [showKeys, setShowKeys] = useState(false)
  const duration = video.duration || 1

  // Technical/EXIF info for this clip — shown here in Review, never on thumbnails.
  const meta = video.meta || {}
  const camera = [meta.make, meta.model].filter(Boolean).join(' ')
  const shotAt = (() => {
    if (!video.shot_at) return null
    const d = new Date(video.shot_at)
    return isNaN(d.getTime()) ? video.shot_at : d.toLocaleString()
  })()
  const infoRows: [string, string][] = [
    ...(shotAt ? [['Shot', shotAt] as [string, string]] : []),
    ...(camera ? [['Camera', camera] as [string, string]] : []),
    ...(meta.lens ? [['Lens', meta.lens] as [string, string]] : []),
    ...(meta.software ? [['Software', meta.software] as [string, string]] : []),
    ...(video.width && video.height ? [['Resolution', `${video.width}×${video.height}`] as [string, string]] : []),
    ...(video.codec ? [['Codec', video.codec] as [string, string]] : []),
    ...(video.fps ? [['Frame rate', `${video.fps.toFixed(2)} fps`] as [string, string]] : []),
    ...(video.size ? [['Size', fmtBytes(video.size)] as [string, string]] : []),
    ...(meta.location ? [['Location', meta.location] as [string, string]] : []),
  ]
  const extraTags = meta.tags ? Object.entries(meta.tags) : []

  const timeAt = (clientX: number) => {
    const rect = barRef.current!.getBoundingClientRect()
    const f = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return f * duration
  }

  const seek = (t: number) => {
    if (videoRef.current) videoRef.current.currentTime = t
    setPlayhead(t)
  }

  // Jump to the deep-linked time once the element can seek (metadata loaded).
  useEffect(() => {
    const el = videoRef.current
    if (!el || initialTime == null) return
    const apply = () => {
      el.currentTime = initialTime
      setPlayhead(initialTime)
    }
    if (el.readyState >= 1) apply()
    else el.addEventListener('loadedmetadata', apply, { once: true })
    return () => el.removeEventListener('loadedmetadata', apply)
  }, [initialTime, video.id])

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const onTime = () => {
      setPlayhead(el.currentTime)
      if (playMode && activeRange && el.currentTime >= activeRange.t_out) {
        if (playMode === 'loop') {
          el.currentTime = activeRange.t_in
        } else {
          el.pause()
          setPlayMode(null)
        }
      }
    }
    el.addEventListener('timeupdate', onTime)
    return () => el.removeEventListener('timeupdate', onTime)
  }, [playMode, activeRange])

  // Play the given range once (pausing at its out point) or on a loop.
  const playRange = (r: VideoRange, mode: 'once' | 'loop') => {
    setActiveRange(r)
    setPlayMode(mode)
    seek(r.t_in)
    videoRef.current?.play()
  }

  const stopPlayback = () => {
    setPlayMode(null)
    videoRef.current?.pause()
  }

  // Clicking the same play/loop control again stops it.
  const togglePlay = (r: VideoRange, mode: 'once' | 'loop') => {
    if (activeRange?.id === r.id && playMode === mode) stopPlayback()
    else playRange(r, mode)
  }

  // Nudge the playhead by one frame (paused), used by the ←/→ arrows.
  const stepFrame = (dir: -1 | 1) => {
    const el = videoRef.current
    if (!el) return
    el.pause()
    seek(Math.min(duration, Math.max(0, el.currentTime + dir / (video.fps || 25))))
  }

  const saveDraft = useCallback(async () => {
    if (draftIn == null || draftOut == null || draftOut - draftIn < 0.1) return
    await api.addRange(pid, video.id, { t_in: draftIn, t_out: draftOut })
    setDraftIn(null)
    setDraftOut(null)
    onChanged()
  }, [draftIn, draftOut, pid, video.id, onChanged])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).tagName === 'INPUT' || (e.target as HTMLElement).tagName === 'TEXTAREA') return
      if (e.key === 'Escape') onClose()
      else if (e.key === 'i' || e.key === 'I') setDraftIn(playhead)
      else if (e.key === 'o' || e.key === 'O') setDraftOut(playhead)
      else if (e.key === 'Enter') saveDraft()
      else if (e.key === 'l' || e.key === 'L') {
        // Toggle looping the selected range (falls back to the first range).
        if (playMode === 'loop') stopPlayback()
        else {
          const target = activeRange ?? video.ranges[0]
          if (target) playRange(target, 'loop')
        }
      }
      else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        if (e.shiftKey) return  // Shift+←/→ steps clips (handled in ReviewPage)
        e.preventDefault()
        stepFrame(e.key === 'ArrowLeft' ? -1 : 1)
      }
      else if (e.key === ' ') {
        e.preventDefault()
        const el = videoRef.current
        if (el) (el.paused ? el.play() : el.pause())
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playhead, onClose, saveDraft, playMode, activeRange, video.ranges])

  const dragHandle = (range: VideoRange, side: 'in' | 'out') => (e: React.PointerEvent) => {
    e.stopPropagation()
    e.preventDefault()
    const move = (ev: PointerEvent) => {
      const t = timeAt(ev.clientX)
      if (side === 'in') range = { ...range, t_in: Math.min(t, range.t_out - 0.1) }
      else range = { ...range, t_out: Math.max(t, range.t_in + 0.1) }
      setActiveRange(range)
      seek(side === 'in' ? range.t_in : range.t_out)
    }
    const up = async () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      await api.updateRange(pid, video.id, range.id, { t_in: range.t_in, t_out: range.t_out, label: range.label })
      onChanged()
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const saveTags = async () => {
    setEditTags(false)
    await api.editAnalysis(pid, video.id, { hashtags: tagsText.split(/[\s,]+/).filter(Boolean) })
    onChanged()
  }

  return (
    <div className="detail-overlay" onClick={onClose}>
      <div className="detail-panel" onClick={(e) => e.stopPropagation()}>
        <div className="detail-header">
          <h3>{video.filename}</h3>
          <StarRating stars={video.stars} onChange={onRate} />
          <button className={video.rejected ? 'danger' : ''} onClick={() => onReject(!video.rejected)}>
            <IcBan /> {video.rejected ? 'Rejected' : 'Reject'}
          </button>
          <button
            className="danger"
            title="Remove this clip from the project (the source file on disk is kept)"
            onClick={() => {
              if (confirm(`Remove "${video.filename}" from the project?\n\nThe source file on disk is not deleted, but a later rescan will re-add it.`)) onDelete()
            }}
          >
            <IcTrash /> Delete
          </button>
          <button onClick={onClose}><IcClose /> Close</button>
        </div>

        <video ref={videoRef} src={media.video(pid, video.id)} controls preload="metadata" />

        <div
          ref={barRef}
          className="trimbar"
          onPointerDown={(e) => seek(timeAt(e.clientX))}
        >
          <img src={media.filmstrip(pid, video.id)} alt="" draggable={false} />
          {video.ranges.map((r) => {
            const shown = activeRange?.id === r.id ? activeRange : r
            return (
              <div
                key={r.id}
                className={`range ${activeRange?.id === r.id ? 'active' : ''}`}
                style={{ left: `${(shown.t_in / duration) * 100}%`, width: `${((shown.t_out - shown.t_in) / duration) * 100}%` }}
                onPointerDown={(e) => {
                  e.stopPropagation()
                  setActiveRange(r)
                  seek(shown.t_in)
                }}
              >
                <div className="handle in" onPointerDown={dragHandle(shown, 'in')} />
                <div className="handle out" onPointerDown={dragHandle(shown, 'out')} />
              </div>
            )
          })}
          {draftIn != null && (
            <div
              className="range"
              style={{
                left: `${(draftIn / duration) * 100}%`,
                width: `${((Math.max(draftOut ?? playhead, draftIn + 0.05) - draftIn) / duration) * 100}%`,
                borderStyle: 'dashed',
              }}
            />
          )}
          <div className="playhead" style={{ left: `${(playhead / duration) * 100}%` }} />
        </div>
        <div className="hint">
          <b>I</b>/<b>O</b> set in/out · <b>Enter</b> save range · <b>Space</b> play
          <button
            type="button"
            className="keys-toggle"
            title="Keyboard shortcuts"
            aria-expanded={showKeys}
            onClick={() => setShowKeys((v) => !v)}
          >
            ?
          </button>
          {draftIn != null && <> — draft: {fmtTime(draftIn)} → {fmtTime(draftOut ?? playhead)}</>}
        </div>
        {showKeys && (
          <dl className="keys-help">
            <dt><b>I</b> / <b>O</b></dt><dd>set in / out point</dd>
            <dt><b>Enter</b></dt><dd>save range from in to out</dd>
            <dt><b>Space</b></dt><dd>play / pause</dd>
            <dt><b>←</b> / <b>→</b></dt><dd>step one frame back / forward</dd>
            <dt><b>Shift+←</b> / <b>Shift+→</b></dt><dd>jump to previous / next clip</dd>
            <dt><b>L</b></dt><dd>loop the selected range</dd>
            <dt><IcPlay /> / <IcLoop /></dt><dd>on a range: play once or loop (click again to stop)</dd>
          </dl>
        )}

        <div className="range-list">
          {video.ranges.length === 0 && <span className="hint">No ranges yet — mark the interesting parts with I/O + Enter.</span>}
          {video.ranges.map((r) => {
            const isActive = activeRange?.id === r.id
            return (
            <div key={r.id} className={`row ${isActive ? 'active' : ''}`}>
              <button
                className={`small ${isActive && playMode === 'once' ? 'primary' : ''}`}
                title="Play this range once (click again to stop)"
                onClick={() => togglePlay(r, 'once')}
              >
                <IcPlay />
              </button>
              <button
                className={`small ${isActive && playMode === 'loop' ? 'primary' : ''}`}
                title="Loop this range (click again to stop)"
                onClick={() => togglePlay(r, 'loop')}
              >
                <IcLoop />
              </button>
              <span>
                {fmtTime(r.t_in)} → {fmtTime(r.t_out)} ({fmtTime(r.t_out - r.t_in)})
              </span>
              <input
                style={{ width: 160, padding: '2px 6px', fontSize: 12 }}
                placeholder="label"
                defaultValue={r.label}
                onBlur={(e) => {
                  if (e.target.value !== r.label) {
                    api.updateRange(pid, video.id, r.id, { t_in: r.t_in, t_out: r.t_out, label: e.target.value }).then(onChanged)
                  }
                }}
              />
              <button className="small danger" onClick={() => api.deleteRange(pid, video.id, r.id).then(onChanged)}>
                <IcClose />
              </button>
            </div>
            )
          })}
        </div>

        <div className="detail-panels-2col">
          <div className="panel">
            <div className="panel-title-row">
              <h2>AI analysis {video.ai_score != null && <span className="ai-score">score <b>{video.ai_score}</b>/10</span>}</h2>
              {aiAvailable && (
                <button
                  className="primary small"
                  disabled={video.status === 'analyzing'}
                  title={video.description ? 'Re-run the AI analysis for this clip' : 'Describe & score this clip with AI'}
                  onClick={() => api.analyze(pid, [video.id], !!video.description).then(onChanged).catch(() => {})}
                >
                  {video.status === 'analyzing' ? 'Analyzing…' : <><IcSparkles /> {video.description ? 'Re-analyze' : 'Analyze with AI'}</>}
                </button>
              )}
            </div>
            <p style={{ margin: '4px 0' }}>{video.description || <span className="hint">No description yet.</span>}</p>
            {(video.energy || video.mood.length > 0 || video.scene || video.shot_type) && (
              <div className="tag-row">
                {video.energy && <span className="tag" title="Motion/action level"><IcBolt /> {video.energy}</span>}
                {video.mood.map((m) => (
                  <span key={m} className="tag" title="Mood"><IcSmile /> {m}</span>
                ))}
                {video.scene && <span className="tag" title="Scene"><IcPin /> {video.scene}</span>}
                {video.shot_type && <span className="tag" title="Shot type"><IcCamera /> {video.shot_type}</span>}
              </div>
            )}
            {editTags ? (
              <div style={{ display: 'flex', gap: 8 }}>
                <input style={{ flex: 1 }} value={tagsText} onChange={(e) => setTagsText(e.target.value)} />
                <button className="primary small" onClick={saveTags}>Save</button>
              </div>
            ) : (
              <div className="tag-row" onDoubleClick={() => setEditTags(true)}>
                {video.hashtags.map((t) => (
                  <span key={t} className="tag">#{t}</span>
                ))}
                <button className="small" onClick={() => setEditTags(true)}>edit tags</button>
              </div>
            )}
            {video.highlights.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <h4 style={{ margin: '4px 0' }}>
                  AI suggestions <span className="hint">— ＋ saves one as an editable range</span>
                </h4>
                {video.highlights.map((h, i) => {
                  const fake: VideoRange = { id: -(i + 1), t_in: h.t_in, t_out: h.t_out, label: h.reason }
                  return (
                    <div key={i} className="row">
                      <button
                        className={`small ${activeRange?.id === fake.id && playMode === 'once' ? 'primary' : ''}`}
                        title="Play this suggested moment (click again to stop)"
                        onClick={() => togglePlay(fake, 'once')}
                      >
                        <IcPlay /> {fmtTime(h.t_in)} → {fmtTime(h.t_out)}
                      </button>
                      <span className="hint" style={{ flex: 1 }}>{h.reason}</span>
                      <button
                        className="small"
                        title="Save as a range you can edit and drag into the montage"
                        onClick={() =>
                          api.addRange(pid, video.id, { t_in: h.t_in, t_out: h.t_out, label: h.reason.slice(0, 60) }).then(onChanged)
                        }
                      >
                        <IcPlus />
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          <div className="panel">
            <div className="panel-title-row">
              <h2>Clip info</h2>
            </div>
            {infoRows.length === 0 ? (
              <span className="hint">No technical metadata found in this file.</span>
            ) : (
              <div className="clip-info">
                {infoRows.map(([label, value]) => (
                  <div key={label} className="row">
                    <span className="hint">{label}</span>
                    <span>{value}</span>
                  </div>
                ))}
              </div>
            )}
            {extraTags.length > 0 && (
              <details style={{ marginTop: 8 }}>
                <summary className="hint" style={{ cursor: 'pointer' }}>
                  Other tags ({extraTags.length})
                </summary>
                <div className="clip-info" style={{ marginTop: 6 }}>
                  {extraTags.map(([k, v]) => (
                    <div key={k} className="row">
                      <span className="hint">{k}</span>
                      <span style={{ wordBreak: 'break-word' }}>{v}</span>
                    </div>
                  ))}
                </div>
              </details>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
