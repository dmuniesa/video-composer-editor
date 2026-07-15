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

/** Grouping key for the bin: source label + subfolder, so identically-named
 *  subfolders in different sources stay distinct. Falls back to the plain
 *  subfolder when a video has no source (legacy rows). */
export function folderKey(v: Video): string {
  const sub = folderOf(v.rel_path)
  if (!v.source_label) return sub
  return sub ? `${v.source_label}/${sub}` : v.source_label
}

/** Unique bin grouping keys present in a video list. */
export function folderKeyList(videos: Video[]): string[] {
  return [...new Set(videos.map(folderKey))].sort()
}

/** Free-text filter: matches filename, description, hashtags and people.
 *  A query starting with '#' matches hashtags only; '@' matches people only. */
export function matchesQuery(v: Video, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  if (q.startsWith('#')) {
    const tag = q.slice(1)
    return tag === '' || v.hashtags.some((t) => t.toLowerCase().includes(tag))
  }
  if (q.startsWith('@')) {
    const name = q.slice(1)
    return name === '' || (v.people ?? []).some((p) => p.name.toLowerCase().includes(name))
  }
  return (
    v.filename.toLowerCase().includes(q) ||
    (v.description ?? '').toLowerCase().includes(q) ||
    v.hashtags.some((t) => t.toLowerCase().includes(q)) ||
    (v.people ?? []).some((p) => p.name.toLowerCase().includes(q))
  )
}
