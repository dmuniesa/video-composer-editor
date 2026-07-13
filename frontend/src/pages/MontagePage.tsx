import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, media, fmtTime, fmtBytes } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { SongInfo, TimelineClip, Track, Video } from '../lib/types'
import InfoTip from '../components/InfoTip'
import ScrubThumb from '../components/ScrubThumb'
import StarRating from '../components/StarRating'
import VideoDetail from '../components/VideoDetail'
import Waveform from '../components/Waveform'
import { folderList, folderOf, matchesQuery } from '../lib/videoFilter'
import { sectionColor } from './MusicPage'

const RULER_H = 26
const TRACK_H = 64
const SNAP_PX = 8

const SEQ_RATIOS = [
  { label: '16:9', w: 16, h: 9 },
  { label: '9:16', w: 9, h: 16 },
  { label: '4:3', w: 4, h: 3 },
  { label: '1:1', w: 1, h: 1 },
  { label: '21:9', w: 21, h: 9 },
  { label: '4:5', w: 4, h: 5 },
]
const SEQ_TIERS = [
  { label: '4K', v: 2160 },
  { label: '1440p', v: 1440 },
  { label: '1080p', v: 1080 },
  { label: '720p', v: 720 },
  { label: '480p', v: 480 },
]

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
  const navigate = useNavigate()
  const [videos, setVideos] = useState<Video[]>([])
  const [ctx, setCtx] = useState<{ x: number; y: number; videoId: number } | null>(null)
  const [detailId, setDetailId] = useState<number | null>(null)
  const [binQuery, setBinQuery] = useState('')
  const [binFolder, setBinFolder] = useState('*')
  const [song, setSong] = useState<SongInfo | null>(null)
  const [peaks, setPeaks] = useState<[number, number][]>([])
  const [tracks, setTracks] = useState<Track[]>([])
  const [pxPerSec, setPxPerSec] = useState(20)
  const [snap, setSnap] = useState(true)
  const [selectedClip, setSelectedClip] = useState<number | null>(null)
  const [clipCtx, setClipCtx] = useState<{ x: number; y: number; clipId: number } | null>(null)
  const [speedInput, setSpeedInput] = useState('1')
  const [compFps, setCompFps] = useState(25)
  const [compW, setCompW] = useState(1920)
  const [compH, setCompH] = useState(1080)
  const [seqOpen, setSeqOpen] = useState(false)
  const [binView, setBinView] = useState<'list' | 'details' | 'grid'>(
    () => (localStorage.getItem('montageBinView') as 'list' | 'details' | 'grid') || 'list',
  )
  const [binWidth, setBinWidth] = useState(() => Number(localStorage.getItem('montageBinWidth')) || 300)
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
  const [composeOpen, setComposeOpen] = useState(false)
  const audioRef = useRef<HTMLAudioElement>(null)
  const previewRef = useRef<HTMLVideoElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const popRef = useRef<HTMLDivElement>(null)

  const refreshTimeline = useCallback(() => {
    api.timeline(pid).then((t) => setTracks(t.tracks)).catch((e) => setToast(e.message))
  }, [pid])

  const refreshVideos = useCallback(() => {
    api.videos(pid).then(setVideos).catch(() => {})
  }, [pid])

  useEffect(() => {
    refreshVideos()
    api.song(pid).then(setSong).catch(() => {})
    api.songPeaks(pid).then((p) => setPeaks(p.peaks)).catch(() => {})
    api.getProject(pid).then((p) => {
      setComposerProvider(p.composer_provider)
      setComposerAvailable(p.composer_available)
      setCompFps(p.composition_fps || 25)
      setCompW(p.composition_width || 1920)
      setCompH(p.composition_height || 1080)
      // start expanded only when it can actually be used
      setComposeOpen(p.composer_available && p.composer_provider !== 'mcp')
    }).catch(() => {})
    refreshTimeline()
  }, [pid, refreshTimeline, refreshVideos])

  useProjectEvents(pid, (e) => {
    if (e.event === 'timeline') refreshTimeline()
    if (e.event === 'videos' || e.event === 'video') refreshVideos()
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

  useEffect(() => {
    localStorage.setItem('montageBinView', binView)
  }, [binView])
  useEffect(() => {
    localStorage.setItem('montageBinWidth', String(binWidth))
  }, [binWidth])

  // ---- composition frame size: resolution tier × aspect ratio ----
  const applySeqSize = (tier: number, ratioW: number, ratioH: number) => {
    // the tier is the short edge; the ratio decides which side is long
    let w: number
    let h: number
    if (ratioW >= ratioH) {
      h = tier
      w = Math.round((tier * ratioW) / ratioH / 2) * 2
    } else {
      w = tier
      h = Math.round((tier * ratioH) / ratioW / 2) * 2
    }
    setCompW(w)
    setCompH(h)
    api.updateProject(pid, { composition_width: w, composition_height: h }).catch((e) => setToast(e.message))
  }
  const curTier = Math.min(compW, compH)
  const curRatio = compW / compH
  const nearestRatio = SEQ_RATIOS.reduce((best, r) =>
    Math.abs(r.w / r.h - curRatio) < Math.abs(best.w / best.h - curRatio) ? r : best,
  )

  const startBinResize = (e: React.PointerEvent) => {
    e.preventDefault()
    const startX = e.clientX
    const startW = binWidth
    const move = (ev: PointerEvent) => {
      setBinWidth(Math.max(220, Math.min(720, startW + ev.clientX - startX)))
    }
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }

  const duration = Math.max(
    song?.duration ?? 0,
    ...tracks.flatMap((t) => t.clips.map((c) => c.timeline_start + c.duration)),
    60,
  )
  const width = duration * pxPerSec

  const videoById = useMemo(() => new Map(videos.map((v) => [v.id, v])), [videos])
  const kept = useMemo(() => videos.filter((v) => !v.rejected), [videos])
  const folders = useMemo(() => folderList(kept), [kept])
  const binVideos = useMemo(
    () =>
      kept
        .filter((v) => matchesQuery(v, binQuery))
        .filter((v) => binFolder === '*' || folderOf(v.rel_path) === binFolder)
        .sort((a, b) => b.stars - a.stars || (b.ai_score ?? 0) - (a.ai_score ?? 0)),
    [kept, binQuery, binFolder],
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
    const speed = clip.speed || 1
    const want = clip.source_in + (playhead - clip.timeline_start) * speed
    if (!pv.src.endsWith(src)) {
      pv.src = src
      pv.currentTime = want
    } else if (Math.abs(pv.currentTime - want) > 0.5 * Math.max(1, speed)) {
      pv.currentTime = want
    }
    if (pv.playbackRate !== speed) pv.playbackRate = speed
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
      if (ctx || clipCtx) {
        if (e.key === 'Escape') {
          setCtx(null)
          setClipCtx(null)
        }
        return
      }
      if (detailId != null) return // the detail drawer has its own shortcuts
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
  }, [selectedClip, pid, refreshTimeline, ctx, clipCtx, detailId])

  // ---- bin context menu ----
  const openCtxMenu = (videoId: number) => (e: React.MouseEvent) => {
    e.preventDefault()
    const v = videoById.get(videoId)
    const estH = 250 + (v?.ranges.length ?? 0) * 30
    setCtx({
      x: Math.min(e.clientX, window.innerWidth - 300),
      y: Math.min(e.clientY, window.innerHeight - estH),
      videoId,
    })
  }

  const rateVideo = (id: number, patch: { stars?: number; rejected?: boolean }) => {
    setVideos((prev) => prev.map((v) => (v.id === id ? { ...v, ...patch } : v)))
    api.rate(pid, [id], patch).catch((e) => {
      setToast(e.message)
      refreshVideos()
    })
  }

  const setClipSpeed = (clip: TimelineClip, speed: number) => {
    if (!isFinite(speed) || speed < 0.05 || speed > 20) {
      setToast('speed must be between 0.05 and 20')
      return
    }
    setSpeedInput(String(speed))
    api.updateClip(pid, clip.id, { speed }).then(refreshTimeline).catch((e) => {
      setToast(e.message)
      refreshTimeline()
    })
  }

  const placeAtPlayhead = (v: Video, tIn: number, tOut: number) => {
    setCtx(null)
    const track = tracks[0]
    if (!track) {
      setToast('no track to place on — add one first')
      return
    }
    api
      .addClip(pid, {
        track_id: track.id,
        video_id: v.id,
        timeline_start: snapTime(playhead),
        source_in: tIn,
        source_out: tOut,
      })
      .then(refreshTimeline)
      .catch((e) => setToast(e.message))
  }

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
    if (e.button !== 0) return // right-click opens the context menu, not a drag
    e.preventDefault()
    setSelectedClip(clip.id)
    const video = videoById.get(clip.video_id)
    const speed = clip.speed || 1
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
        // timeline deltas convert to source seconds at the clip's speed
        const maxIn = state.orig.source_out - 0.2 * speed
        let newStart = snapTime(state.orig.timeline_start + dt)
        const delta = newStart - state.orig.timeline_start
        let newIn = state.orig.source_in + delta * speed
        if (newIn < 0) {
          newStart -= newIn / speed
          newIn = 0
        }
        if (newIn > maxIn) {
          newStart -= (newIn - maxIn) / speed
          newIn = maxIn
        }
        p.timeline_start = newStart
        p.source_in = newIn
      } else {
        const end = snapTime(state.orig.timeline_start + state.orig.duration + dt)
        let newOut = state.orig.source_in + Math.max(0.2, end - state.orig.timeline_start) * speed
        if (video?.duration) newOut = Math.min(newOut, video.duration)
        p.source_out = newOut
      }
      p.duration = (p.source_out - p.source_in) / speed
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
      <div className={`bin bin-view-${binView}`} style={{ width: binWidth }}>
        <div className="compose-panel">
          <div className="compose-head" onClick={() => setComposeOpen((v) => !v)}>
            <span className="compose-title">
              ✨ Auto-compose
              <span className={`chip ${composerAvailable && composerProvider !== 'mcp' ? 'ok' : ''}`}>
                {composerProvider}
              </span>
            </span>
            <InfoTip>
              <b>AI auto-compose</b>
              <p>
                Writes your instructions once and the whole project (clips, song sections, beats,
                current timeline) is sent to the composer provider, which places clips on the
                timeline — they appear purple, live.
              </p>
              <p>
                With <b>Claude via MCP</b> (the default) this button stays disabled: compose by
                talking to Claude with the MCP server registered (see the Guide). Pick agy or an
                OpenAI endpoint in <b>Settings → Composer provider</b> to compose from here.
              </p>
            </InfoTip>
            <span className="hint">{composeOpen ? '▾' : '▸'}</span>
          </div>
          {composeOpen && (
            <>
              <textarea
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                placeholder="e.g. “best clips on the choruses, calm shots on the verses”"
                rows={2}
              />
              <button
                className="primary"
                onClick={compose}
                disabled={composing || !composerAvailable || composerProvider === 'mcp'}
                title={
                  composerProvider === 'mcp'
                    ? 'Composer provider is Claude via MCP — see the ? help'
                    : !composerAvailable
                      ? `provider “${composerProvider}” unavailable — check Settings`
                      : ''
                }
              >
                {composing ? 'Composing…' : 'Compose'}
              </button>
            </>
          )}
          {composeResult && <div className="hint">{composeResult}</div>}
        </div>
        <div className="bin-head">
          <span className="bin-title">
            Clips <span className="hint">{binVideos.length}</span>
          </span>
          <div className="bin-view-toggle">
            <button className={binView === 'list' ? 'active' : ''} title="compact list" onClick={() => setBinView('list')}>☰</button>
            <button className={binView === 'details' ? 'active' : ''} title="list with details" onClick={() => setBinView('details')}>≣</button>
            <button className={binView === 'grid' ? 'active' : ''} title="large thumbnails" onClick={() => setBinView('grid')}>▦</button>
          </div>
          <InfoTip>
            <b>Bin tips</b>
            <ul>
              <li><b>Drag</b> a clip — or one of its ranges — onto a track.</li>
              <li><b>Right-click</b> for actions: place at playhead, details, Review, rate, reject.</li>
              <li><b>Double-click</b> opens the detail (player, ranges, tags).</li>
              <li>Hover a thumbnail to <b>scrub</b> through the clip.</li>
              <li>Filter with free text, <code>#hashtag</code> or a subfolder.</li>
              <li>Purple clips on the timeline were placed by AI.</li>
            </ul>
          </InfoTip>
        </div>
        <div className="bin-filter">
          <input
            placeholder="filter — text or #tag"
            value={binQuery}
            onChange={(e) => setBinQuery(e.target.value)}
          />
          {folders.length > 1 && (
            <select value={binFolder} onChange={(e) => setBinFolder(e.target.value)} title="subfolder">
              <option value="*">all folders</option>
              {folders.map((f) => (
                <option key={f} value={f}>{f === '' ? '(root)' : f}</option>
              ))}
            </select>
          )}
          {(binQuery || binFolder !== '*') && (
            <span className="hint">
              {binVideos.length}/{kept.length}
              <button
                className="small"
                style={{ marginLeft: 6 }}
                onClick={() => {
                  setBinQuery('')
                  setBinFolder('*')
                }}
              >
                ✕
              </button>
            </span>
          )}
        </div>
        <div className={`bin-list bin-view-${binView}`}>
          {binVideos.map((v) => (
            <div key={v.id} className="bin-entry" onContextMenu={openCtxMenu(v.id)}>
              <div
                className="bin-item"
                draggable
                onDoubleClick={() => setDetailId(v.id)}
                onDragStart={(e) =>
                  e.dataTransfer.setData(
                    'application/x-montage',
                    JSON.stringify({ video_id: v.id, t_in: 0, t_out: v.duration }),
                  )
                }
              >
                <ScrubThumb pid={pid} videoId={v.id} duration={v.duration}>
                  {binView === 'grid' && <span className="bin-grid-dur">{fmtTime(v.duration)}</span>}
                </ScrubThumb>
                <div className="meta">
                  <div className="name" title={v.rel_path}>{v.filename}</div>
                  <div className="sub">
                    {'★'.repeat(v.stars)}{v.ai_score != null ? ` · AI ${v.ai_score}` : ''} · {fmtTime(v.duration)}
                  </div>
                  {binView === 'details' && (
                    <div className="sub">
                      {v.width > 0 ? `${v.width}×${v.height}` : '—'}
                      {v.fps > 0 ? ` · ${Math.round(v.fps)} fps` : ''}
                      {v.codec ? ` · ${v.codec}` : ''}
                      {v.size > 0 ? ` · ${fmtBytes(v.size)}` : ''}
                    </div>
                  )}
                  <div className="sub">
                    {v.hashtags.slice(0, 3).map((t) => (
                      <span key={t} className="bin-tag" onClick={() => setBinQuery(`#${t}`)}>
                        #{t}{' '}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
              {binView !== 'grid' &&
                v.ranges.map((r) => (
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
        {binVideos.length === 0 && kept.length > 0 && (
          <div className="hint" style={{ textAlign: 'center', padding: 12 }}>
            no clips match the filter
          </div>
        )}
      </div>

      <div className="bin-resizer" onPointerDown={startBinResize} title="drag to resize the clip list" />

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
          <div className="seq-menu">
            <button className="small" onClick={() => setSeqOpen((v) => !v)} title="composition settings — written to the exported sequence">
              ⚙ {compW}×{compH} · {compFps} fps ▾
            </button>
            {seqOpen && (
              <>
                <div className="seq-overlay" onMouseDown={() => setSeqOpen(false)} />
                <div className="seq-dropdown">
                  <div className="seq-title">Sequence</div>
                  <label className="seq-row">
                    <span>Frame rate</span>
                    <select
                      value={compFps}
                      onChange={(e) => {
                        const fps = Number(e.target.value)
                        setCompFps(fps)
                        api.updateProject(pid, { composition_fps: fps }).catch((err) => setToast(err.message))
                      }}
                    >
                      {[23.976, 24, 25, 29.97, 30, 50, 59.94, 60].map((f) => (
                        <option key={f} value={f}>{f} fps</option>
                      ))}
                    </select>
                  </label>
                  <label className="seq-row">
                    <span>Resolution</span>
                    <select
                      value={curTier}
                      onChange={(e) => applySeqSize(Number(e.target.value), nearestRatio.w, nearestRatio.h)}
                    >
                      {SEQ_TIERS.map((t) => (
                        <option key={t.v} value={t.v}>{t.label}</option>
                      ))}
                    </select>
                  </label>
                  <label className="seq-row">
                    <span>Aspect ratio</span>
                    <select
                      value={nearestRatio.label}
                      onChange={(e) => {
                        const r = SEQ_RATIOS.find((x) => x.label === e.target.value)!
                        applySeqSize(curTier, r.w, r.h)
                      }}
                    >
                      {SEQ_RATIOS.map((r) => (
                        <option key={r.label} value={r.label}>{r.label}</option>
                      ))}
                    </select>
                  </label>
                  <div className="seq-row hint"><span>Output size</span><span>{compW} × {compH}</span></div>
                </div>
              </>
            )}
          </div>
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
                      onContextMenu={(e) => {
                        e.preventDefault()
                        e.stopPropagation()
                        setSelectedClip(clip.id)
                        setSpeedInput(String(clip.speed || 1))
                        setClipCtx({
                          x: Math.min(e.clientX, window.innerWidth - 320),
                          y: Math.min(e.clientY, window.innerHeight - 340),
                          clipId: clip.id,
                        })
                      }}
                    >
                      {video && (
                        <img className="film" src={media.thumb(pid, clip.video_id)} alt="" draggable={false} />
                      )}
                      <div className="label">
                        {video?.filename ?? clip.video_id} · {fmtTime(shown.duration)}
                        {(clip.speed || 1) !== 1 ? ` · ${clip.speed}×` : ''}
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
              <span>speed {selected.speed || 1}×</span>
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
      {ctx && (() => {
        const v = videoById.get(ctx.videoId)
        if (!v) return null
        return (
          <>
            <div
              className="ctx-overlay"
              onMouseDown={() => setCtx(null)}
              onContextMenu={(e) => {
                e.preventDefault()
                setCtx(null)
              }}
            />
            <div className="ctx-menu" style={{ left: ctx.x, top: ctx.y }}>
              <div className="ctx-header">
                <span className="ctx-title">{v.filename}</span>
                <span className="hint">
                  {fmtTime(v.duration)} · {v.width}×{v.height} · {Math.round(v.fps)} fps
                  {v.ai_score != null ? ` · AI ${v.ai_score}` : ''}
                </span>
              </div>
              <button className="ctx-item" onClick={() => placeAtPlayhead(v, 0, v.duration)}>
                <span>➕ Place at playhead</span>
                <span className="hint">{fmtTime(playhead)}</span>
              </button>
              {v.ranges.map((r) => (
                <button key={r.id} className="ctx-item" onClick={() => placeAtPlayhead(v, r.t_in, r.t_out)}>
                  <span>◳ Place “{r.label || 'range'}”</span>
                  <span className="hint">{fmtTime(r.t_in)}–{fmtTime(r.t_out)}</span>
                </button>
              ))}
              <div className="ctx-sep" />
              <button
                className="ctx-item"
                onClick={() => {
                  setDetailId(v.id)
                  setCtx(null)
                }}
              >
                <span>🎞 Details — player, ranges & tags</span>
              </button>
              <button className="ctx-item" onClick={() => navigate(`/p/${pid}/review?video=${v.id}`)}>
                <span>⭐ Show in Review</span>
                <span className="hint">→</span>
              </button>
              <div className="ctx-sep" />
              <div className="ctx-rate">
                <StarRating stars={v.stars} onChange={(stars) => rateVideo(v.id, { stars })} />
                <button
                  className="small danger"
                  onClick={() => {
                    rateVideo(v.id, { rejected: true })
                    setCtx(null)
                  }}
                >
                  ✕ reject
                </button>
              </div>
            </div>
          </>
        )
      })()}
      {clipCtx && (() => {
        const cclip = tracks.flatMap((t) => t.clips).find((c) => c.id === clipCtx.clipId)
        if (!cclip) return null // clip vanished (SSE refresh)
        const v = videoById.get(cclip.video_id)
        const speed = cclip.speed || 1
        const canSplit =
          cclip.timeline_start + 0.05 < playhead && playhead < cclip.timeline_start + cclip.duration - 0.05
        const nearestBeat = snapPoints.length
          ? snapPoints.reduce((best, p) =>
              Math.abs(p - cclip.timeline_start) < Math.abs(best - cclip.timeline_start) ? p : best,
            )
          : null
        return (
          <>
            <div
              className="ctx-overlay"
              onMouseDown={() => setClipCtx(null)}
              onContextMenu={(e) => {
                e.preventDefault()
                setClipCtx(null)
              }}
            />
            <div className="ctx-menu" style={{ left: clipCtx.x, top: clipCtx.y }}>
              <div className="ctx-header">
                <span className="ctx-title">{v?.filename ?? `clip #${cclip.id}`}</span>
                <span className="hint">
                  {fmtTime(cclip.duration)}
                  {v ? ` · ${v.width}×${v.height} · ${Math.round(v.fps)} fps` : ''}
                  {speed !== 1 ? ` · ${speed}×` : ''}
                </span>
              </div>
              <div className="ctx-speed">
                <span className="hint">speed</span>
                {[0.25, 0.5, 0.75, 1, 1.5, 2].map((s) => (
                  <button
                    key={s}
                    className={`small ${speed === s ? 'primary' : ''}`}
                    onClick={() => setClipSpeed(cclip, s)}
                  >
                    {s}×
                  </button>
                ))}
                <input
                  type="number"
                  min={0.05}
                  max={20}
                  step={0.05}
                  value={speedInput}
                  onChange={(e) => setSpeedInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') setClipSpeed(cclip, Number(speedInput))
                  }}
                  onBlur={() => {
                    const n = Number(speedInput)
                    if (n && n !== speed) setClipSpeed(cclip, n)
                  }}
                />
              </div>
              <div className="ctx-sep" />
              <button
                className="ctx-item"
                disabled={!canSplit}
                title={canSplit ? '' : 'move the playhead inside this clip'}
                onClick={() => {
                  api.splitClip(pid, cclip.id, playhead).then(refreshTimeline).catch((e) => setToast(e.message))
                  setClipCtx(null)
                }}
              >
                <span>✂ Split at playhead</span>
                <span className="hint">{fmtTime(playhead)}</span>
              </button>
              <button
                className="ctx-item"
                disabled={nearestBeat == null}
                onClick={() => {
                  if (nearestBeat == null) return
                  api
                    .updateClip(pid, cclip.id, { timeline_start: nearestBeat })
                    .then(refreshTimeline)
                    .catch((e) => setToast(e.message))
                  setClipCtx(null)
                }}
              >
                <span>🧲 Snap to nearest beat</span>
                {nearestBeat != null && <span className="hint">{fmtTime(nearestBeat)}</span>}
              </button>
              <div className="ctx-sep" />
              <button
                className="ctx-item"
                onClick={() => {
                  setDetailId(cclip.video_id)
                  setClipCtx(null)
                }}
              >
                <span>🎞 Details — player, ranges & tags</span>
              </button>
              <button className="ctx-item" onClick={() => navigate(`/p/${pid}/review?video=${cclip.video_id}`)}>
                <span>⭐ Show in Review</span>
                <span className="hint">→</span>
              </button>
              <div className="ctx-sep" />
              <button
                className="ctx-item"
                onClick={() => {
                  api.deleteClip(pid, cclip.id).then(refreshTimeline).catch((e) => setToast(e.message))
                  setSelectedClip(null)
                  setClipCtx(null)
                }}
              >
                <span style={{ color: 'var(--danger)' }}>🗑 Delete clip</span>
                <span className="hint">Del</span>
              </button>
            </div>
          </>
        )
      })()}
      {detailId != null && videoById.get(detailId) && (
        <VideoDetail
          pid={pid}
          video={videoById.get(detailId)!}
          onClose={() => setDetailId(null)}
          onChanged={refreshVideos}
          onRate={(stars) => rateVideo(detailId, { stars })}
          onReject={(rejected) => rateVideo(detailId, { rejected })}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
