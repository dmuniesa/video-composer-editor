import { useCallback, useEffect, useRef, useState } from 'react'
import { api, media, fmtTime } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { SongInfo } from '../lib/types'
import Waveform from '../components/Waveform'

const SECTION_COLORS: Record<string, string> = {
  intro: '#4f8cff',
  verse: '#4fbf67',
  'pre-chorus': '#c9a13d',
  chorus: '#e5534b',
  drop: '#e5534b',
  bridge: '#9b6fd0',
  instrumental: '#5bc8c4',
  outro: '#8a93a6',
}

export function sectionColor(label: string): string {
  return SECTION_COLORS[label] ?? '#666e80'
}

export default function MusicPage({ pid }: { pid: string }) {
  const [song, setSong] = useState<SongInfo | null>(null)
  const [peaks, setPeaks] = useState<[number, number][]>([])
  const [error, setError] = useState('')
  const [width, setWidth] = useState(900)
  const [playhead, setPlayhead] = useState(0)
  const wrapRef = useRef<HTMLDivElement>(null)
  const audioRef = useRef<HTMLAudioElement>(null)

  const refresh = useCallback(() => {
    api.song(pid).then(setSong).catch((e) => setError(e.message))
    api.songPeaks(pid).then((p) => setPeaks(p.peaks)).catch(() => {})
  }, [pid])
  useEffect(refresh, [refresh])
  useProjectEvents(pid, (e) => {
    if (e.event === 'song') refresh()
  })

  // The wave-wrap sits behind the `if (!song) return` early returns, so on
  // first mount wrapRef.current is null and an empty-deps effect never
  // attaches the observer — leaving `width` stuck at 900 and the waveform
  // compressed. Re-run once `song` is present so the ref is bound.
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const obs = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width))
    obs.observe(el)
    return () => obs.disconnect()
  }, [song])

  if (error && !song) return <div className="empty-note">{error} — choose a song on the Setup page.</div>
  if (!song) return <div className="empty-note">Loading…</div>

  const duration = song.duration || 1
  const waveHeight = 110
  const lyrics = song.lyrics
  const hasVocals = lyrics?.status === 'ready'
  const activeLine = hasVocals
    ? lyrics.segments.findIndex((l) => l.start <= playhead && playhead < l.end)
    : -1

  return (
    <div className="music-page">
      <div className="stat-row">
        <span className="crumb" style={{ margin: 0 }}>{song.path}</span>
        <span>status <b>{song.status}</b></span>
        {song.bpm != null && <span><b>{song.bpm.toFixed(1)}</b> BPM</span>}
        <span><b>{fmtTime(song.duration)}</b></span>
        <span><b>{song.beats.length}</b> beats</span>
        <button className="small" onClick={() => api.songReanalyze(pid).catch((e) => setError(e.message))}>Re-analyze</button>
        <button className="small" onClick={() => api.songLabel(pid).catch((e) => setError(e.message))}>Label with Gemini</button>
        <button
          className="small"
          disabled={lyrics?.status === 'transcribing'}
          title={
            song.lyrics_enabled
              ? 'Transcribe the lyrics locally with Whisper'
              : 'Enable lyrics analysis in Settings first'
          }
          onClick={() => api.songTranscribe(pid).catch((e) => setError(e.message))}
        >
          {lyrics?.status === 'transcribing' ? 'Transcribing…' : 'Transcribe lyrics'}
        </button>
        {lyrics && lyrics.status === 'ready' && (
          <span>
            lyrics <b>{lyrics.segments.length}</b> lines
            {lyrics.language ? ` (${lyrics.language})` : ''}
          </span>
        )}
      </div>
      {song.status === 'error' && <div className="error-text">{song.error}</div>}
      {lyrics?.status === 'error' && <div className="error-text">Lyrics: {lyrics.error}</div>}

      <audio ref={audioRef} src={media.song(pid)} controls style={{ width: '100%' }} onTimeUpdate={(e) => setPlayhead(e.currentTarget.currentTime)} />

      <div className="wave-wrap" ref={wrapRef}>
        <div
          style={{ position: 'relative', cursor: 'crosshair' }}
          onClick={(e) => {
            const rect = e.currentTarget.getBoundingClientRect()
            const t = ((e.clientX - rect.left) / rect.width) * duration
            if (audioRef.current) audioRef.current.currentTime = t
            setPlayhead(t)
          }}
        >
          {/* section bands */}
          <div style={{ position: 'relative', height: 24 }}>
            {song.sections.map((s) => (
              <div
                key={s.id}
                title={`${s.label || 'section'} ${fmtTime(s.start)}–${fmtTime(s.end)}`}
                style={{
                  position: 'absolute',
                  left: `${(s.start / duration) * 100}%`,
                  width: `${((s.end - s.start) / duration) * 100}%`,
                  top: 2,
                  bottom: 2,
                  background: sectionColor(s.label),
                  opacity: 0.75,
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
          {/* vocal / melody-only strip (from the Whisper transcription) */}
          {hasVocals && (
            <div style={{ position: 'relative', height: 8 }} title="green = vocals, teal = melody only">
              {lyrics.vocal_ranges.map((r, i) => (
                <div
                  key={`v${i}`}
                  style={{
                    position: 'absolute',
                    left: `${(r.start / duration) * 100}%`,
                    width: `${((r.end - r.start) / duration) * 100}%`,
                    top: 1,
                    bottom: 1,
                    background: '#4fbf67',
                    borderRadius: 2,
                  }}
                />
              ))}
              {lyrics.instrumental_ranges.map((r, i) => (
                <div
                  key={`i${i}`}
                  style={{
                    position: 'absolute',
                    left: `${(r.start / duration) * 100}%`,
                    width: `${((r.end - r.start) / duration) * 100}%`,
                    top: 1,
                    bottom: 1,
                    background: '#5bc8c4',
                    borderRadius: 2,
                    opacity: 0.8,
                  }}
                />
              ))}
            </div>
          )}
          <Waveform peaks={peaks} width={width} height={waveHeight} />
          {/* beats */}
          <svg width={width} height={14} style={{ display: 'block' }}>
            {song.beats.map((b, i) => (
              <line
                key={i}
                x1={(b / duration) * width}
                x2={(b / duration) * width}
                y1={0}
                y2={song.downbeats.includes(b) ? 14 : 7}
                stroke={song.downbeats.includes(b) ? '#f3c245' : '#555c6b'}
                strokeWidth={1}
              />
            ))}
          </svg>
          <div
            style={{
              position: 'absolute',
              top: 0,
              bottom: 0,
              width: 1.5,
              background: '#ff5555',
              left: `${(playhead / duration) * 100}%`,
              pointerEvents: 'none',
            }}
          />
        </div>
      </div>

      <div className="panel">
        <h2>Sections</h2>
        <table className="section-table">
          <thead>
            <tr>
              <th>start</th><th>end</th><th>length</th><th>energy</th>{hasVocals && <th>vocals</th>}<th>label</th><th>source</th><th></th>
            </tr>
          </thead>
          <tbody>
            {song.sections.map((s) => (
              <tr key={s.id}>
                <td>{fmtTime(s.start)}</td>
                <td>{fmtTime(s.end)}</td>
                <td>{fmtTime(s.end - s.start)}</td>
                <td>{Math.round(s.energy * 100)}%</td>
                {hasVocals && (
                  <td title="fraction of the section with singing">
                    {s.vocal_ratio != null && s.vocal_ratio < 0.1
                      ? '🎸 melody'
                      : s.vocal_ratio != null
                        ? `🎤 ${Math.round(s.vocal_ratio * 100)}%`
                        : '—'}
                  </td>
                )}
                <td>
                  <select
                    value={s.label}
                    onChange={(e) => api.updateSection(pid, s.id, { label: e.target.value }).then(refresh)}
                    style={{ background: sectionColor(s.label), color: '#fff', border: 'none' }}
                  >
                    <option value="">(unlabeled)</option>
                    {Object.keys(SECTION_COLORS).map((l) => (
                      <option key={l} value={l}>{l}</option>
                    ))}
                  </select>
                </td>
                <td>{s.source}</td>
                <td style={{ display: 'flex', gap: 6 }}>
                  <button
                    className="small"
                    title="Split at playhead"
                    disabled={!(s.start + 0.5 < playhead && playhead < s.end - 0.5)}
                    onClick={() => api.splitSection(pid, s.id, playhead).then(refresh).catch((e) => setError(e.message))}
                  >
                    split @ {fmtTime(playhead)}
                  </button>
                  <button
                    className="small danger"
                    title="Merge into neighbour"
                    onClick={() => api.deleteSection(pid, s.id).then(refresh).catch((e) => setError(e.message))}
                  >
                    merge
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {hasVocals && (
        <div className="panel">
          <h2>
            Lyrics{' '}
            <span className="hint" style={{ fontWeight: 'normal' }}>
              (Whisper {lyrics.model || ''}
              {lyrics.language ? `, ${lyrics.language}` : ''} — click a line to seek)
            </span>
          </h2>
          {lyrics.segments.length === 0 ? (
            <p className="hint">No sung lines detected — the track looks fully instrumental.</p>
          ) : (
            <div style={{ maxHeight: 260, overflowY: 'auto' }}>
              {lyrics.segments.map((l, i) => (
                <div
                  key={i}
                  onClick={() => {
                    if (audioRef.current) audioRef.current.currentTime = l.start
                    setPlayhead(l.start)
                  }}
                  style={{
                    display: 'flex',
                    gap: 10,
                    padding: '2px 6px',
                    cursor: 'pointer',
                    borderRadius: 4,
                    background: i === activeLine ? 'rgba(79,140,255,0.25)' : 'transparent',
                  }}
                >
                  <span className="hint" style={{ minWidth: 44, textAlign: 'right' }}>
                    {fmtTime(l.start)}
                  </span>
                  <span>{l.text}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      {error && song && <div className="toast">{error}</div>}
    </div>
  )
}
