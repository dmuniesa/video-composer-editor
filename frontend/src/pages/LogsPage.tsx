import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { LogRecord } from '../lib/types'

const LEVELS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR'] as const
type Level = (typeof LEVELS)[number]

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: 'var(--text-dim)',
  INFO: 'var(--text)',
  WARNING: 'var(--star)',
  ERROR: 'var(--danger)',
  CRITICAL: 'var(--danger)',
}

const RANK: Record<string, number> = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 }
const MAX_KEPT = 2000

function fmtClock(epoch: number): string {
  const d = new Date(epoch * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

export default function LogsPage({ pid }: { pid: string }) {
  const [records, setRecords] = useState<LogRecord[]>([])
  const [minLevel, setMinLevel] = useState<Level>('ALL')
  const [follow, setFollow] = useState(true)
  const [paused, setPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const pausedRef = useRef(paused)
  pausedRef.current = paused

  useEffect(() => {
    api.logs().then((r) => setRecords(r.records)).catch(() => {})
  }, [])

  useProjectEvents(pid, (e) => {
    if (e.event !== 'log' || pausedRef.current) return
    const rec = e.data as unknown as LogRecord
    setRecords((prev) => {
      const next = [...prev, rec]
      return next.length > MAX_KEPT ? next.slice(next.length - MAX_KEPT) : next
    })
  })

  const shown = useMemo(() => {
    if (minLevel === 'ALL') return records
    const floor = RANK[minLevel]
    return records.filter((r) => (RANK[r.level] ?? 0) >= floor)
  }, [records, minLevel])

  useEffect(() => {
    if (follow && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [shown, follow])

  const clear = async () => {
    try {
      await api.clearLogs()
    } catch {
      /* ignore */
    }
    setRecords([])
  }

  const download = () => {
    const text = records
      .map((r) => `${fmtClock(r.time)} ${r.level} ${r.logger}: ${r.message}`)
      .join('\n')
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const a = document.createElement('a')
    a.href = url
    a.download = 'montage-logs.txt'
    a.click()
    URL.revokeObjectURL(url)
  }

  const hasDebug = records.some((r) => r.level === 'DEBUG')

  return (
    <div className="logs-page">
      <div className="logs-toolbar">
        <span className="logs-title">Backend logs</span>
        <select value={minLevel} onChange={(e) => setMinLevel(e.target.value as Level)}>
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l === 'ALL' ? 'All levels' : `${l}+`}
            </option>
          ))}
        </select>
        <label className="logs-check">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
          Follow
        </label>
        <button className="small" onClick={() => setPaused((p) => !p)}>
          {paused ? '▶ Resume' : '⏸ Pause'}
        </button>
        <span className="spacer" />
        <span className="hint">{shown.length} shown / {records.length} total</span>
        <button className="small" onClick={download} disabled={records.length === 0}>
          Download
        </button>
        <button className="small danger" onClick={clear}>
          Clear
        </button>
      </div>

      {!hasDebug && (
        <div className="logs-note hint">
          Tip: for the full AI prompts and raw model responses, enable{' '}
          <b>Verbose (debug) logging</b> in <Link to={`/p/${pid}/settings`}>Settings</Link>.
        </div>
      )}

      <div className="logs-scroll" ref={scrollRef}>
        {shown.length === 0 ? (
          <div className="empty-note">
            No log lines yet. Trigger an AI analysis (Review → Analyze) and watch them appear here.
          </div>
        ) : (
          shown.map((r) => (
            <div key={r.seq} className="logs-line">
              <span className="logs-time">{fmtClock(r.time)}</span>
              <span className="logs-level" style={{ color: LEVEL_COLOR[r.level] ?? 'var(--text)' }}>
                {r.level}
              </span>
              <span className="logs-logger">{r.logger.replace(/^app\.(services\.)?/, '')}</span>
              <span className="logs-msg">{r.message}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
