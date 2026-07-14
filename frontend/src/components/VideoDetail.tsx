import { useCallback, useEffect, useRef, useState } from 'react'
import { api, media, fmtTime } from '../lib/api'
import type { Video, VideoRange } from '../lib/types'
import StarRating from './StarRating'

interface Props {
  pid: string
  video: Video
  aiAvailable?: boolean
  onClose: () => void
  onChanged: () => void
  onRate: (stars: number) => void
  onReject: (rejected: boolean) => void
  onDelete: () => void
}

/** Detail drawer: player + trim bar with in/out handles over a filmstrip.
 *  Keyboard: I = set in, O = set out, Enter = save range, L = loop range. */
export default function VideoDetail({ pid, video, aiAvailable, onClose, onChanged, onRate, onReject, onDelete }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const [playhead, setPlayhead] = useState(0)
  const [draftIn, setDraftIn] = useState<number | null>(null)
  const [draftOut, setDraftOut] = useState<number | null>(null)
  const [activeRange, setActiveRange] = useState<VideoRange | null>(null)
  const [looping, setLooping] = useState(false)
  const [editTags, setEditTags] = useState(false)
  const [tagsText, setTagsText] = useState(video.hashtags.join(' '))
  const duration = video.duration || 1

  const timeAt = (clientX: number) => {
    const rect = barRef.current!.getBoundingClientRect()
    const f = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
    return f * duration
  }

  const seek = (t: number) => {
    if (videoRef.current) videoRef.current.currentTime = t
    setPlayhead(t)
  }

  useEffect(() => {
    const el = videoRef.current
    if (!el) return
    const onTime = () => {
      setPlayhead(el.currentTime)
      if (looping && activeRange && el.currentTime >= activeRange.t_out) {
        el.currentTime = activeRange.t_in
      }
    }
    el.addEventListener('timeupdate', onTime)
    return () => el.removeEventListener('timeupdate', onTime)
  }, [looping, activeRange])

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
      else if (e.key === 'l' || e.key === 'L') setLooping((v) => !v)
      else if (e.key === ' ') {
        e.preventDefault()
        const el = videoRef.current
        if (el) (el.paused ? el.play() : el.pause())
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [playhead, onClose, saveDraft])

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
            {video.rejected ? 'Rejected ✕' : 'Reject'}
          </button>
          <button
            className="danger"
            title="Remove this clip from the project (the source file on disk is kept)"
            onClick={() => {
              if (confirm(`Remove "${video.filename}" from the project?\n\nThe source file on disk is not deleted, but a later rescan will re-add it.`)) onDelete()
            }}
          >
            Delete
          </button>
          <button onClick={onClose}>Close</button>
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
          <b>I</b> set in · <b>O</b> set out · <b>Enter</b> save range · <b>L</b> loop selected · <b>Space</b> play/pause
          {draftIn != null && <> — draft: {fmtTime(draftIn)} → {fmtTime(draftOut ?? playhead)}</>}
        </div>

        <div className="range-list">
          {video.ranges.length === 0 && <span className="hint">No ranges yet — mark the interesting parts with I/O + Enter.</span>}
          {video.ranges.map((r) => (
            <div key={r.id} className={`row ${activeRange?.id === r.id ? 'active' : ''}`}>
              <button
                className="small"
                onClick={() => {
                  setActiveRange(r)
                  setLooping(true)
                  seek(r.t_in)
                  videoRef.current?.play()
                }}
              >
                ▶
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
                ✕
              </button>
            </div>
          ))}
        </div>

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
                {video.status === 'analyzing' ? 'Analyzing…' : video.description ? '✨ Re-analyze' : '✨ Analyze with AI'}
              </button>
            )}
          </div>
          <p style={{ margin: '4px 0' }}>{video.description || <span className="hint">No description yet.</span>}</p>
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
        </div>
      </div>
    </div>
  )
}
