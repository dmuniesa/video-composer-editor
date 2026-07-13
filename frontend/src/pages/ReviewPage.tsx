import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../lib/api'
import { useProjectEvents } from '../lib/sse'
import type { Video } from '../lib/types'
import VideoCard from '../components/VideoCard'
import VideoDetail from '../components/VideoDetail'
import { folderList, folderOf, matchesQuery } from '../lib/videoFilter'

export default function ReviewPage({ pid }: { pid: string }) {
  const [videos, setVideos] = useState<Video[]>([])
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [lastClicked, setLastClicked] = useState<number | null>(null)
  const [openId, setOpenId] = useState<number | null>(null)
  const [minStars, setMinStars] = useState(0)
  const [hideRejected, setHideRejected] = useState(false)
  const [tagFilter, setTagFilter] = useState('')
  const [query, setQuery] = useState('')
  const [folder, setFolder] = useState('*')
  const [sortBy, setSortBy] = useState<'name' | 'ai' | 'stars' | 'duration'>('name')
  const [toast, setToast] = useState('')
  const [searchParams, setSearchParams] = useSearchParams()

  const refresh = useCallback(() => {
    api.videos(pid).then(setVideos).catch((e) => setToast(e.message))
  }, [pid])
  useEffect(refresh, [refresh])
  useProjectEvents(pid, (e) => {
    if (e.event === 'video' || e.event === 'videos') refresh()
  })

  // Deep link (?video=ID) from the montage bin: open that clip's detail.
  useEffect(() => {
    const q = searchParams.get('video')
    if (!q || videos.length === 0) return
    const id = Number(q)
    if (videos.some((v) => v.id === id)) {
      setOpenId(id)
      setSelected(new Set([id]))
      setLastClicked(id)
    }
    setSearchParams({}, { replace: true })
  }, [videos, searchParams, setSearchParams])

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 4000)
    return () => clearTimeout(t)
  }, [toast])

  const folders = useMemo(() => folderList(videos), [videos])

  const shown = useMemo(() => {
    let list = videos
    if (minStars > 0) list = list.filter((v) => v.stars >= minStars)
    if (hideRejected) list = list.filter((v) => !v.rejected)
    if (tagFilter) list = list.filter((v) => v.hashtags.includes(tagFilter))
    if (query) list = list.filter((v) => matchesQuery(v, query))
    if (folder !== '*') list = list.filter((v) => folderOf(v.rel_path) === folder)
    const by = {
      name: (a: Video, b: Video) => a.filename.localeCompare(b.filename),
      ai: (a: Video, b: Video) => (b.ai_score ?? -1) - (a.ai_score ?? -1),
      stars: (a: Video, b: Video) => b.stars - a.stars,
      duration: (a: Video, b: Video) => b.duration - a.duration,
    }[sortBy]
    return [...list].sort(by)
  }, [videos, minStars, hideRejected, tagFilter, query, folder, sortBy])

  const rate = useCallback(
    (ids: number[], patch: { stars?: number; rejected?: boolean }) => {
      // Optimistic update, server confirms via SSE.
      setVideos((prev) => prev.map((v) => (ids.includes(v.id) ? { ...v, ...patch } : v)))
      api.rate(pid, ids, patch).catch((e) => {
        setToast(e.message)
        refresh()
      })
    },
    [pid, refresh],
  )

  const clickCard = (video: Video, e: React.MouseEvent) => {
    const next = new Set(selected)
    if (e.shiftKey && lastClicked != null) {
      const ids = shown.map((v) => v.id)
      const a = ids.indexOf(lastClicked)
      const b = ids.indexOf(video.id)
      if (a !== -1 && b !== -1) {
        for (let i = Math.min(a, b); i <= Math.max(a, b); i++) next.add(ids[i])
      }
    } else if (e.ctrlKey || e.metaKey) {
      if (next.has(video.id)) next.delete(video.id)
      else next.add(video.id)
    } else {
      next.clear()
      next.add(video.id)
    }
    setSelected(next)
    setLastClicked(video.id)
  }

  // Keyboard: 0-5 rate selection, X toggle reject, A select all, Esc clear.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (openId != null) return
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      const ids = [...selected]
      if (ids.length === 0) return
      if (/^[0-5]$/.test(e.key)) rate(ids, { stars: Number(e.key) })
      else if (e.key === 'x' || e.key === 'X') {
        const anyKept = videos.some((v) => ids.includes(v.id) && !v.rejected)
        rate(ids, { rejected: anyKept })
      } else if (e.key === 'Escape') setSelected(new Set())
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selected, videos, rate, openId])

  const open = openId != null ? videos.find((v) => v.id === openId) : undefined

  return (
    <div className="review-layout">
      <div className="review-main">
        <div className="filter-bar">
          <span>{shown.length}/{videos.length} videos</span>
          <input
            className="filter-search"
            placeholder="search — text or #tag"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {folders.length > 1 && (
            <label>
              folder{' '}
              <select value={folder} onChange={(e) => setFolder(e.target.value)}>
                <option value="*">all</option>
                {folders.map((f) => (
                  <option key={f} value={f}>{f === '' ? '(root)' : f}</option>
                ))}
              </select>
            </label>
          )}
          <label>
            min ★{' '}
            <select value={minStars} onChange={(e) => setMinStars(Number(e.target.value))}>
              {[0, 1, 2, 3, 4, 5].map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <label>
            <input type="checkbox" checked={hideRejected} onChange={(e) => setHideRejected(e.target.checked)} /> hide rejected
          </label>
          <label>
            sort{' '}
            <select value={sortBy} onChange={(e) => setSortBy(e.target.value as typeof sortBy)}>
              <option value="name">name</option>
              <option value="ai">AI score</option>
              <option value="stars">stars</option>
              <option value="duration">duration</option>
            </select>
          </label>
          {tagFilter && (
            <span className="tag active" onClick={() => setTagFilter('')}>
              #{tagFilter} ✕
            </span>
          )}
          <span className="hint">click = select · shift/ctrl = multi · 1-5 rate · X reject · dbl-click open</span>
        </div>

        {videos.length === 0 ? (
          <div className="empty-note">No videos yet — scan a folder on the Setup page.</div>
        ) : (
          <div className="video-grid">
            {shown.map((v) => (
              <VideoCard
                key={v.id}
                pid={pid}
                video={v}
                selected={selected.has(v.id)}
                onSelect={(e) => clickCard(v, e)}
                onOpen={() => setOpenId(v.id)}
                onRate={(stars) => rate(selected.has(v.id) && selected.size > 1 ? [...selected] : [v.id], { stars })}
                onTagClick={(t) => setTagFilter(t === tagFilter ? '' : t)}
                activeTag={tagFilter}
              />
            ))}
          </div>
        )}
      </div>

      {open && (
        <VideoDetail
          pid={pid}
          video={open}
          onClose={() => setOpenId(null)}
          onChanged={refresh}
          onRate={(stars) => rate([open.id], { stars })}
          onReject={(rejected) => rate([open.id], { rejected })}
        />
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  )
}
