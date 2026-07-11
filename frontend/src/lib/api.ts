import type {
  AppSettings,
  FsListing,
  JobInfo,
  ProjectInfo,
  SongInfo,
  Track,
  Video,
  VideoRange,
} from './types'

async function req<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      detail = (await res.json()).detail ?? detail
    } catch {
      /* not json */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const api = {
  fsList: (path: string) =>
    req<FsListing>(`/api/fs/list?path=${encodeURIComponent(path)}`),

  listProjects: () => req<{ id: string; video_dir: string; name: string }[]>('/api/projects'),
  createProject: (video_dir: string) =>
    req<ProjectInfo>('/api/projects', { method: 'POST', body: JSON.stringify({ video_dir }) }),
  getProject: (pid: string) => req<ProjectInfo>(`/api/projects/${pid}`),
  scan: (pid: string) =>
    req<{ added: number; removed: number; total: number }>(`/api/projects/${pid}/scan`, {
      method: 'POST',
    }),
  analyze: (pid: string, video_ids?: number[], force = false) =>
    req<{ queued: number }>(`/api/projects/${pid}/analyze`, {
      method: 'POST',
      body: JSON.stringify({ video_ids: video_ids ?? null, force }),
    }),
  setSong: (pid: string, path: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song`, {
      method: 'POST',
      body: JSON.stringify({ path }),
    }),
  jobs: (pid: string, active = true) =>
    req<JobInfo[]>(`/api/projects/${pid}/jobs?active=${active}`),

  settings: () => req<AppSettings>('/api/settings'),
  saveSettings: (s: AppSettings) => {
    const { ai_status: _ignored, ...body } = s
    return req<AppSettings>('/api/settings', { method: 'PUT', body: JSON.stringify(body) })
  },
  testAI: () =>
    req<{ ok: boolean; provider: string | null; error?: string }>('/api/settings/test_ai', {
      method: 'POST',
    }),
  reextract: (pid: string) =>
    req<{ queued: number }>(`/api/projects/${pid}/reextract`, { method: 'POST' }),

  videos: (pid: string) => req<Video[]>(`/api/projects/${pid}/videos`),
  rate: (pid: string, video_ids: number[], patch: { stars?: number; rejected?: boolean }) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/videos/rating`, {
      method: 'POST',
      body: JSON.stringify({ video_ids, ...patch }),
    }),
  editAnalysis: (pid: string, vid: number, patch: { description?: string; hashtags?: string[] }) =>
    req<Video>(`/api/projects/${pid}/videos/${vid}/analysis`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  addRange: (pid: string, vid: number, r: { t_in: number; t_out: number; label?: string }) =>
    req<VideoRange>(`/api/projects/${pid}/videos/${vid}/ranges`, {
      method: 'POST',
      body: JSON.stringify(r),
    }),
  updateRange: (pid: string, vid: number, rid: number, r: { t_in: number; t_out: number; label: string }) =>
    req<VideoRange>(`/api/projects/${pid}/videos/${vid}/ranges/${rid}`, {
      method: 'PATCH',
      body: JSON.stringify(r),
    }),
  deleteRange: (pid: string, vid: number, rid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/videos/${vid}/ranges/${rid}`, { method: 'DELETE' }),

  song: (pid: string) => req<SongInfo>(`/api/projects/${pid}/song`),
  songPeaks: (pid: string) => req<{ peaks: [number, number][] }>(`/api/projects/${pid}/song/peaks`),
  songReanalyze: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/reanalyze`, { method: 'POST' }),
  songLabel: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/label`, { method: 'POST' }),
  updateSection: (pid: string, sid: number, patch: { label?: string; start?: number; end?: number }) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/sections/${sid}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  splitSection: (pid: string, sid: number, at: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/sections/${sid}/split`, {
      method: 'POST',
      body: JSON.stringify({ at }),
    }),
  deleteSection: (pid: string, sid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/sections/${sid}`, { method: 'DELETE' }),

  timeline: (pid: string) => req<{ tracks: Track[] }>(`/api/projects/${pid}/timeline`),
  addTrack: (pid: string) => req<Track>(`/api/projects/${pid}/tracks`, { method: 'POST' }),
  removeTrack: (pid: string, tid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/tracks/${tid}`, { method: 'DELETE' }),
  addClip: (
    pid: string,
    clip: { track_id: number; video_id: number; timeline_start: number; source_in: number; source_out: number },
  ) => req<{ id: number }>(`/api/projects/${pid}/clips`, { method: 'POST', body: JSON.stringify(clip) }),
  updateClip: (
    pid: string,
    cid: number,
    patch: { timeline_start?: number; track_id?: number; source_in?: number; source_out?: number },
  ) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/clips/${cid}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  deleteClip: (pid: string, cid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/clips/${cid}`, { method: 'DELETE' }),
}

export const media = {
  video: (pid: string, vid: number) => `/media/${pid}/video/${vid}`,
  thumb: (pid: string, vid: number) => `/media/${pid}/thumb/${vid}`,
  filmstrip: (pid: string, vid: number) => `/media/${pid}/filmstrip/${vid}`,
  song: (pid: string) => `/media/${pid}/song`,
}

export function fmtTime(s: number): string {
  if (!isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`
}
