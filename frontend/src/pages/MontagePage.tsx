import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, media, fmtTime } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { SongInfo, TimelineClip, Track, Video } from '../lib/types'
import ScrubThumb from '../components/ScrubThumb'
import Waveform from '../components/Waveform'
import { sectionColor } from './MusicPage'

const RULER_H = 26
const TRACK_H = 64
const SNAP_PX = 8

interface DragState {
  clipId: number
  mode: 'move' | 'trim-l' | 'trim-r'
  startX: number
  orig: TimelineClip
  trackId: number
  /** local preview while dragging */
  preview: TimelineClip
  previewTrackId: number
}

export default function MontagePage({ pid }: { pid: string }) {
  const [videos, setVideos] = useState<Video[]>([])
  const [song, setSong] = useState<SongInfo | null>(null)
  const [peaks, setPeaks] = useState<[number, number][]>([])
  const [tracks, setTracks] = useState<Track[]>([])
  const [pxPerSec, setPxPerSec] = useState(20)
  const [snap, setSnap] = useState(true)
  const [selectedClip, setSelectedClip] = useState<number | null>(null)
  const [drag, setDrag] = useState<DragState | null>(null)
  const [dropTrack, setDropTrack] = useState<number | null>(null)
  const [playhead, setPlayhead] = useState(0)
  const [previewOpen, setPreviewOpen] = useState(true)
  const [previewLowRes, setPreviewLowRes] = useState(true)
  /** null = default position (anchored bottom-right via CSS) */
  const [popPos, setPopPos] = useState<{ x: number; y: number } | null>(null)
  const [playing, setPlaying] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [toast, setToast] = useState('')
  const [composerProvider, setComposerProvider] = useState('mcp')
  const [composerAvailable, setComposerAvailable] = useState(false)
  const [instructions, setInstructions] = useState('')
  const [composing, setComposing] = useState(false)
  const [composeResult, setComposeResult] = useState('')
  const audioRef = useRef<HTMLAudioElement>(null)
  const previewRef = useRef<HTMLVideoElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  const refreshTimeline = useCallback(() => {
    api.timeline(pid).then((t) => setTracks(t.tracks)).catch((e) => setToast(e.message))
  }, [pid])

  useEffect(() => {
    api.videos(pid).then(setVideos).catch(() => {})
    api.song(pid).then(setSong).catch(() => {})
    api.songPeaks(pid).then((p) => setPeaks(p.peaks)).catch(() => {})
    api.getProject(pid).then((p) => {
      setComposerProvider(p.composer_provider)
      setComposerAvailable(p.composer_available)
    }).catch(() => {})
    refreshTimeline()
  }, [pid, refreshTimeline])

  useProjectEvents(pid, (e) => {
    if (e.event === 'timeline') refreshTimeline()
    if (e.event === 'videos' || e.event === 'video') api.videos(pid).then(setVideos).catch(() => {})
    if (e.event === 'compose') {
      setComposing(false)
      const d = e.data as {
        status: string
        applied?: number
        errors?: string[]
        summary?: string
        error?: string
      }
      setComposeResult(
        d.status === 'done'
          ? `✓ ${d.applied} action(s) applied${d.errors?.length ? `, ${d.errors.length} rejected` : ''}${d.summary ? ` — ${d.summary}` : ''}`
          : `✗ ${d.error}`,
      )
    }
  })

  const compose = () => {
    setComposeResult('')
    setComposing(true)
    api.compose(pid, instructions).catch((err) => {
      setComposing(false)
      setToast(err.message)
    })
  }

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(t)
  }, [toast])

  const duration = Math.max(
    song?.duration ?? 0,
    ...tracks.flatMap((t) => t.clips.map((c) => c.timeline_start + c.duration)),
    60,
  )
  const width = duration * pxPerSec

  const videoById = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos])
  const binVideos = useMemo(
    () =>
      videos
        .filter((v) => !v.rejected)
        .sort((a, b) => b.stars - a.stars || (b.ai_score ?? 0) - (a.ai_score ?? 0)),
    [videos],
  )

  const snapPoints = useMemo(() => {
    if (!song) return []
    const pts = [...song.beats]
    for (const s of song.sections) pts.push(s.start, s.end)
    return pts.sort((a, b) => a - b)
  }, [song])

  const snapTime = useCallback(
    (t: number) => {
      if (!snap || snapPoints.length === 0) return Math.max(0, t)
      const threshold = SNAP_PX / pxPerSec
      let best = t
      let bestDist = threshold
      for (const p of snapPoints) {
        const d = Math.abs(p - t)
        if (d < bestDist) {
          best = p
          bestDist = d
        }
      }
      return Math.max(0, best)
    },
    [snap, snapPoints, pxPerSec],
  )

  // ---- audio/video preview ----
  const clipAt = useCallback(
    (t: number): TimelineClip | null => {
      // Topmost track wins where clips overlap across tracks.
      for (const track of tracks) {
        const c = track.clips.find((c) => c.timeline_start <= t && t < c.timeline_start + c.duration)
        if (c) return c
      }
      return null
    },
    [tracks],
  )

  // The <audio> element only mounts once the song has loaded, so this must
  // re-run on `song` — with [] it would bind before the element exists.
  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    let raf = 0
    const tick = () => {
      setPlayhead(el.currentTime)
      raf = requestAnimationFrame(tick)
    }
    const onPlay = () => {
      setPlaying(true)
      raf = requestAnimationFrame(tick)
    }
    const onPause = () => {
      setPlaying(false)
      cancelAnimationFrame(raf)
    }
    el.addEventListener('play', onPlay)
    el.addEventListener('pause', onPause)
    if (!el.paused) onPlay()
    return () => {
      el.removeEventListener('play', onPlay)
      el.removeEventListener('pause', onPause)
      cancelAnimationFrame(raf)
    }
  }, [song])

  // drag the preview popup around by its header
  const startPopDrag = (e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return
    const pop = popRef.current
    const parent = pop?.offsetParent as HTMLElement | null
    if (!pop || !parent) return
    e.preventDefault()
    const rect = pop.getBoundingClientRect()
    const prect = parent.getBoundingClientRect()
    const offX = e.clientX - rect.left
    const offY = e.clientY - rect.top
    const move = (ev: PointerEvent) => {
      const x = Math.max(0, Math.min(ev.clientX - prect.left - offX, prect.width - rect.width))
      const y = Math.max(0, Math.min(ev.clientY - prect.top - offY, prect.height - rect.height))
      setPopPos({ x, y })
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const togglePlay = () => {
    const a = audioRef.current
    if (!a) return
    if (a.paused) a.play()
    else a.pause()
  }

  useEffect(() => {
    const pv = previewRef.current
    if (!pv) return
    const clip = clipAt(playhead)
    void previewOpen // re-sync the <video> right after the popup (re)mounts
    if (!clip) {
      pv.pause()
      pv.removeAttribute('src')
      pv.load()
      return
    }
    const src = previewLowRes ? media.preview(pid, clip.video_id) : media.video(pid, clip.video_id)
    const want = clip.source_in + (playhead - clip.timeline_start)
    if (!pv.src.endsWith(src)) {
      pv.src = src
      pv.currentTime = want
    } else if (Math.abs(pv.currentTime - want) > 0.5) {
      pv.currentTime = want
    }
    const playing = audioRef.current && !audioRef.current.paused
    if (playing && pv.paused) pv.play().catch(() => {})
    if (!playing && !pv.paused) pv.pause()
  }, [playhead, clipAt, pid, previewOpen, previewLowRes])

  const seek = (t: number) => {
    if (audioRef.current) audioRef.current.currentTime = Math.max(0, t)
    setPlayhead(Math.max(0, t))
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === ' ') {
        e.preventDefault()
        togglePlay()
      } else if ((e.key === 'Delete' || e.key === 'Backspace') && selectedClip != null) {
        api.deleteClip(pid, selectedClip).then(refreshTimeline).catch((err) => setToast(err.message))
        setSelectedClip(null)
      } else if (e.key === 's' || e.key === 'S') setSnap((v) => !v)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedClip, pid, refreshTimeline])

  // ---- drop from bin ----
  const onDrop = (track: Track) => (e: React.DragEvent) => {
    e.preventDefault()
    setDropTrack(null)
    const raw = e.dataTransfer.getData('application/x-montage')
    if (!raw) return
    const data = JSON.parse(raw) as { video_id: number; t_in: number; t_out: number }
    const rect = e.currentTarget.getBoundingClientRect()
    const t = snapTime((e.clientX - rect.left) / pxPerSec)
    api
      .addClip(pid, {
        track_id: track.id,
        video_id: data.video_id,
        timeline_start: t,
        source_in: data.t_in,
        source_out: data.t_out,
      })
      .then(refreshTimeline)
      .catch((err) => setToast(err.message))
  }

  // ---- clip drag / trim ----
  const startDrag = (clip: TimelineClip, trackId: number, mode: DragState['mode']) => (e: React.PointerEvent) => {
    e.stopPropagation()
    e.preventDefault()
    setSelectedClip(clip.id)
    const video = videoById.get(clip.video_id)
    const startX = e.clientX
    const startY = e.clientY
    const state: DragState = {
      clipId: clip.id,
      mode,
      startX,
      orig: clip,
      trackId,
      preview: clip,
      previewTrackId: trackId,
    }
    setDrag(state)

    const move = (ev: PointerEvent) => {
      const dt = (ev.clientX - startX) / pxPerSec
      const p = { ...state.orig }
      let previewTrackId = state.trackId
      if (mode === 'move') {
        p.timeline_start = snapTime(state.orig.timeline_start + dt)
        // vertical track change
        const dy = ev.clientY - startY
        const rows = Math.round(dy / TRACK_H)
        const idx = tracks.findIndex((t) => t.id === state.trackId)
        const newIdx = Math.min(tracks.length - 1, Math.max(0, idx + rows))
        previewTrackId = tracks[newIdx].id
      } else if (mode === 'trim-l') {
        const maxIn = state.orig.source_out - 0.2
        let newStart = snapTime(state.orig.timeline_start + dt)
        let delta = newStart - state.orig.timeline_start
        let newIn = state.orig.source_in + delta
        if (newIn < 0) {
          newStart -= newIn
          newIn = 0
        }
        if (newIn > maxIn) {
          newStart -= newIn - maxIn
          newIn = maxIn
        }
        p.timeline_start = newStart
        p.source_in = newIn
      } else {
        const end = snapTime(state.orig.timeline_start + state.orig.duration + dt)
        let newOut = state.orig.source_in + Math.max(0.2, end - state.orig.timeline_start)
        if (video?.duration) newOut = Math.min(newOut, video.duration)
        p.source_out = newOut
      }
      p.duration = p.source_out - p.source_in
      state.preview = p
      state.previewTrackId = previewTrackId
      setDrag({ ...state })
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      setDrag(null)
      const p = state.preview
      const changed =
        p.timeline_start !== state.orig.timeline_start ||
        p.source_in !== state.orig.source_in ||
        p.source_out !== state.orig.source_out ||
        state.previewTrackId !== state.trackId
      if (!changed) return
      api
        .updateClip(pid, clip.id, {
          timeline_start: p.timeline_start,
          source_in: p.source_in,
          source_out: p.source_out,
          track_id: state.previewTrackId,
        })
        .then(refreshTimeline)
        .catch((err) => {
          setToast(err.message)
          refreshTimeline()
        })
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  // ---- ruler ticks ----
  const tickStep = pxPerSec >= 60 ? 1 : pxPerSec >= 25 ? 2 : pxPerSec >= 10 ? 5 : 15
  const ticks: number[] = []
  for (let t = 0; t <= duration; t += tickStep) ticks.push(t)

  const selected = selectedClip != null
    ? tracks.flatMap((t) => t.clips).find((c) => c.id === selectedClip)
    : undefined

  return (
    <div className="montage-layout">
      <div className="bin">
        <div className="compose-panel">
          <textarea
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Instructions for the AI, e.g. “use the best clips on the choruses, calm shots on the verses”"
            rows={3}
          />
          <button
            className="primary"
            onClick={compose}
            disabled={composing || !composerAvailable}
            title={composerProvider === 'mcp' ? 'Composer provider is Claude via MCP — see Settings' : ''}
          >
            {composing ? 'Composing…' : `Auto-compose (${composerProvider})`}
          </button>
          {composerProvider === 'mcp' && (
            <div className="hint">
              Composer provider is set to Claude via MCP — compose by talking to Claude as before,
              or switch provider in Settings.
            </div>
          )}
          {composerProvider !== 'mcp' && !composerAvailable && (
            <div className="hint">
              Composer provider “{composerProvider}” is not available — check Settings.
            </div>
          )}
          {composeResult && <div className="hint">{composeResult}</div>}
        </div>
        <div className="hint">
          Drag a video (full clip) or one of its ranges onto a track. Purple clips were placed by
          AI (Claude/agy/OpenAI).
        </div>
        {binVideos.map((v) => (
          <div key={v.id}>
            <div
              className="bin-item"
              draggable
              onDragStart={(e) =>
                e.dataTransfer.setData(
                  'application/x-montage',
                  JSON.stringify({ video_id: v.id, t_in: 0, t_out: v.duration }),
                )
              }
            >
              <ScrubThumb pid={pid} videoId={v.id} duration={v.duration} />
              <div className="meta">
                <div className="name">{v.filename}</div>
                <div className="sub">
                  {'★'.repeat(v.stars)}{v.ai_score != null ? ` · AI ${v.ai_score}` : ''} · {fmtTime(v.duration)}
                </div>
                <div className="sub">{v.hashtags.slice(0, 3).map((t) => `#${t}`).join(' ')}</div>
              </div>
            </div>
            {v.ranges.map((r) => (
              <div
                key={r.id}
                className="bin-range"
                draggable
                onDragStart={(e) =>
                  e.dataTransfer.setData(
                    'application/x-montage',
                    JSON.stringify({ video_id: v.id, t_in: r.t_in, t_out: r.t_out }),
                  )
                }
              >
                ◳ {r.label || 'range'} {fmtTime(r.t_in)}–{fmtTime(r.t_out)}
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="montage-main">
        <div className="montage-toolbar">
          <button className="small" onClick={() => setPxPerSec((z) => Math.min(120, z * 1.4))}>＋ zoom</button>
          <button className="small" onClick={() => setPxPerSec((z) => Math.max(4, z / 1.4))}>－ zoom</button>
          <label>
            <input type="checkbox" checked={snap} onChange={(e) => setSnap(e.target.checked)} /> snap to beats (S)
          </label>
          <button className="small" onClick={() => api.addTrack(pid).then(refreshTimeline)}>+ track</button>
          {tracks.length > 1 && (
            <button
              className="small"
              onClick={() => api.removeTrack(pid, tracks[tracks.length - 1].id).then(refreshTimeline).catch((e) => setToast(e.message))}
            >
              − track
            </button>
          )}
          <span className="spacer" style={{ flex: 1 }} />
          <button className="small" onClick={() => seek(0)} title="go to start">⏮</button>
          <button className="small" onClick={togglePlay} title="play/pause (Space)" disabled={!song}>
            {playing ? '⏸' : '▶'}
          </button>
          <span className="hint">{fmtTime(playhead)}</span>
          <button className="small" onClick={() => setPreviewOpen((v) => !v)}>
            {previewOpen ? '✕ preview' : '▶ preview'}
          </button>
          <div className="export-menu">
            <button className="primary" onClick={() => setExportOpen((v) => !v)}>
              Export ▾
            </button>
            {exportOpen && (
              <div className="export-dropdown" onClick={() => setExportOpen(false)}>
                <a href={`/api/projects/${pid}/export.xml`} download>
                  <b>Premiere Pro</b>
                  <span className="hint">montage.xml · File → Import</span>
                </a>
                <a href={`/api/projects/${pid}/export-resolve.xml`} download>
                  <b>DaVinci Resolve</b>
                  <span className="hint">montage-resolve.xml · File → Import → Timeline</span>
                </a>
                <a href={`/api/projects/${pid}/export.fcpxml`} download>
                  <b>Final Cut Pro</b>
                  <span className="hint">montage.fcpxml · File → Import → XML</span>
                </a>
              </div>
            )}
          </div>
        </div>

        {song && <audio ref={audioRef} src={media.song(pid)} style={{ display: 'none' }} />}

        {previewOpen && (
          <div
            className="preview-pop"
            ref={popRef}
            style={popPos ? { left: popPos.x, top: popPos.y, right: 'auto', bottom: 'auto' } : undefined}
          >
            <div className="preview-pop-head" onPointerDown={startPopDrag}>
              <span>preview · {fmtTime(playhead)}</span>
              <span style={{ display: 'flex', gap: 4 }}>
                <button
                  className="small"
                  onClick={() => setPreviewLowRes((v) => !v)}
                  title={previewLowRes ? 'low-res proxy (smooth) — click for full quality' : 'full quality — click for smooth low-res'}
                >
                  {previewLowRes ? 'SD' : 'HD'}
                </button>
                <button className="small" onClick={() => setPreviewOpen(false)} title="close">✕</button>
              </span>
            </div>
            <video ref={previewRef} muted playsInline />
            <div className="preview-pop-controls">
              <button className="small" onClick={() => seek(0)} title="go to start">⏮</button>
              <button className="small" onClick={togglePlay} title="play/pause (Space)" disabled={!song}>
                {playing ? '⏸' : '▶'}
              </button>
              <input
                type="range"
                min={0}
                max={duration}
                step={0.1}
                value={playhead}
                onChange={(e) => seek(Number(e.target.value))}
              />
            </div>
          </div>
        )}

        <div className="timeline-scroll" ref={scrollRef}>
          <div className="timeline-inner" style={{ width: width + 60 }}>
            {/* ruler */}
            <div className="tl-ruler" onPointerDown={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              seek((e.clientX - rect.left + (scrollRef.current?.scrollLeft ?? 0) * 0) / pxPerSec)
            }}>
              <svg width={width} height={RULER_H}>
                {ticks.map((t) => (
                  <g key={t}>
                    <line x1={t * pxPerSec} x2={t * pxPerSec} y1={RULER_H - 8} y2={RULER_H} stroke="#555c6b" />
                    <text x={t * pxPerSec + 3} y={RULER_H - 10} fill="#9aa1b0" fontSize={10}>
                      {fmtTime(t)}
                    </text>
                  </g>
                ))}
              </svg>
            </div>

            {/* audio row: sections + waveform + beats */}
            <div className="tl-audio" onPointerDown={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              seek((e.clientX - rect.left) / pxPerSec)
            }}>
              {song && (
                <>
                  <div style={{ position: 'relative', height: 18 }}>
                    {song.sections.map((s) => (
                      <div
                        key={s.id}
                        title={s.label}
                        style={{
                          position: 'absolute',
                          left: s.start * pxPerSec,
                          width: (s.end - s.start) * pxPerSec,
                          top: 1,
                          bottom: 1,
                          background: sectionColor(s.label),
                          opacity: 0.8,
                          borderRadius: 3,
                          fontSize: 10,
                          paddingLeft: 4,
                          overflow: 'hidden',
                          whiteSpace: 'nowrap',
                          color: '#fff',
                        }}
                      >
                        {s.label}
                      </div>
                    ))}
                  </div>
                  <Waveform peaks={peaks} width={width} height={54} color="#3d5a8f" />
                  <svg width={width} height={12} style={{ display: 'block' }}>
                    {song.beats.map((b, i) => (
                      <line
                        key={i}
                        x1={b * pxPerSec}
                        x2={b * pxPerSec}
                        y1={0}
                        y2={song.downbeats.includes(b) ? 12 : 6}
                        stroke={song.downbeats.includes(b) ? '#f3c245' : '#4a5160'}
                      />
                    ))}
                  </svg>
                </>
              )}
              {!song && <div className="empty-note" style={{ padding: 20 }}>No song analyzed yet — see the Music page.</div>}
            </div>

            {/* video tracks */}
            {tracks.map((track) => (
              <div
                key={track.id}
                className={`tl-track ${dropTrack === track.id ? 'drop-target' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDropTrack(track.id)
                }}
                onDragLeave={() => setDropTrack((cur) => (cur === track.id ? null : cur))}
                onDrop={onDrop(track)}
                onPointerDown={(e) => {
                  if (e.target === e.currentTarget) {
                    const rect = e.currentTarget.getBoundingClientRect()
                    seek((e.clientX - rect.left) / pxPerSec)
                    setSelectedClip(null)
                  }
                }}
              >
                <span className="hint" style={{ position: 'absolute', left: 6, top: 4, pointerEvents: 'none' }}>
                  {track.name}
                </span>
                {track.clips.map((clip) => {
                  const isDragged = drag?.clipId === clip.id
                  const shown = isDragged ? drag.preview : clip
                  const shownTrack = isDragged ? drag.previewTrackId : track.id
                  if (isDragged && shownTrack !== track.id) return null
                  const video = videoById.get(clip.video_id)
                  return (
                    <div
                      key={clip.id}
                      className={`tl-clip ${selectedClip === clip.id ? 'selected' : ''} ${clip.placed_by !== 'user' ? 'by-ai' : ''}`}
                      style={{ left: shown.timeline_start * pxPerSec, width: Math.max(shown.duration * pxPerSec, 8) }}
                      onPointerDown={startDrag(clip, track.id, 'move')}
                    >
                      {video && (
                        <img className="film" src={media.thumb(pid, clip.video_id)} alt="" draggable={false} />
                      )}
                      <div className="label">
                        {video?.filename ?? clip.video_id} · {fmtTime(shown.duration)}
                      </div>
                      <div className="trim l" onPointerDown={startDrag(clip, track.id, 'trim-l')} />
                      <div className="trim r" onPointerDown={startDrag(clip, track.id, 'trim-r')} />
                    </div>
                  )
                })}
                {/* ghost while dragging across tracks */}
                {drag && drag.previewTrackId === track.id && drag.trackId !== track.id && (
                  <div
                    className="tl-clip"
                    style={{
                      left: drag.preview.timeline_start * pxPerSec,
                      width: Math.max(drag.preview.duration * pxPerSec, 8),
                      opacity: 0.6,
                    }}
                  >
                    {videoById.has(drag.preview.video_id) && (
                      <img className="film" src={media.thumb(pid, drag.preview.video_id)} alt="" draggable={false} />
                    )}
                  </div>
                )}
              </div>
            ))}

            <div className="tl-playhead" style={{ left: playhead * pxPerSec }} />
          </div>
        </div>

        <div className="inspector">
          {selected ? (
            <>
              <span>clip #{selected.id} · {videoById.get(selected.video_id)?.filename}</span>
              <span>start {fmtTime(selected.timeline_start)}</span>
              <span>src {fmtTime(selected.source_in)} → {fmtTime(selected.source_out)}</span>
              <span>len {fmtTime(selected.duration)}</span>
              <span>by {selected.placed_by}</span>
              <button
                className="small danger"
                onClick={() => {
                  api.deleteClip(pid, selected.id).then(refreshTimeline)
                  setSelectedClip(null)
                }}
              >
                delete (Del)
              </button>
            </>
          ) : (
            <span>
              Space = play · click clip to select · drag edges to trim · Del = delete ·
              auto-compose with the panel on the left, or connect Claude via MCP (see README)
            </span>
          )}
        </div>
      </div>
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
