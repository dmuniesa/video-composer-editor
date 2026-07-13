import type { Video } from './types'

/** Directory part of a video's rel_path ('' = project root), normalized to '/'. */
export function folderOf(relPath: string): string {
  const p = relPath.replace(/\\/g, '/')
  const i = p.lastIndexOf('/')
  return i === -1 ? '' : p.slice(0, i)
}

/** Unique subfolders present in a video list, root first. */
export function folderList(videos: Video[]): string[] {
  return [...new Set(videos.map((v) => folderOf(v.rel_path)))].sort()
}

/** Free-text filter: matches filename, description and hashtags.
 *  A query starting with '#' matches hashtags only. */
export function matchesQuery(v: Video, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (q.startsWith('#')) {
    const tag = q.slice(1)
    return tag === '' || v.hashtags.some((t) => t.toLowerCase().includes(tag))
  }
  return (
    v.filename.toLowerCase().includes(q) ||
    (v.description ?? '').toLowerCase().includes(q) ||
    v.hashtags.some((t) => t.toLowerCase().includes(q))
  )
}
