import type {
  AppSettings,
  ExcludedFile,
  FaceInfo,
  FsListing,
  JobInfo,
  LogRecord,
  PeopleResponse,
  Person,
  ProjectInfo,
  SongInfo,
  Source,
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

  /** Open the OS-native folder/file dialog. Returns `{ ok: false }` when no
   *  native dialog is available so the caller can fall back to the in-app
   *  browser; on success `path` is null if the user cancelled. */
  pickPath: async (
    kind: 'dir' | 'audio',
    initial = '',
  ): Promise<{ ok: true; path: string | null } | { ok: false }> => {
    const res = await fetch('/api/fs/pick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ kind, initial }),
    })
    if (res.status === 501) return { ok: false }
    if (!res.ok) {
      let detail = res.statusText
      try {
        detail = (await res.json()).detail ?? detail
      } catch {
        /* not json */
      }
      throw new Error(detail)
    }
    return { ok: true, path: (await res.json()).path }
  },

  listProjects: () => req<{ id: string; video_dir: string; name: string }[]>('/api/projects'),
  createProject: (project_dir: string, name = '') =>
    req<ProjectInfo>('/api/projects', { method: 'POST', body: JSON.stringify({ project_dir, name }) }),
  importProject: (project_dir: string) =>
    req<ProjectInfo>('/api/projects/import', { method: 'POST', body: JSON.stringify({ project_dir }) }),
  getProject: (pid: string) => req<ProjectInfo>(`/api/projects/${pid}`),

  sources: (pid: string) => req<Source[]>(`/api/projects/${pid}/sources`),
  addSource: (pid: string, path: string, label?: string) =>
    req<ProjectInfo>(`/api/projects/${pid}/sources`, {
      method: 'POST',
      body: JSON.stringify({ path, label }),
    }),
  updateSource: (pid: string, sid: number, patch: { path?: string; label?: string }) =>
    req<ProjectInfo>(`/api/projects/${pid}/sources/${sid}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  removeSource: (pid: string, sid: number) =>
    req<ProjectInfo>(`/api/projects/${pid}/sources/${sid}`, { method: 'DELETE' }),
  updateProject: (
    pid: string,
    patch: { name?: string; composition_fps?: number; composition_width?: number; composition_height?: number },
  ) => req<ProjectInfo>(`/api/projects/${pid}`, { method: 'PATCH', body: JSON.stringify(patch) }),
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

  logs: (pid: string) => req<{ records: LogRecord[] }>(`/api/projects/${pid}/logs`),
  clearLogs: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/logs/clear`, { method: 'POST' }),

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
  clearAnalysis: (pid: string) =>
    req<{ cleared: number }>(`/api/projects/${pid}/clear_analysis`, { method: 'POST' }),

  videos: (pid: string) => req<Video[]>(`/api/projects/${pid}/videos`),
  rate: (pid: string, video_ids: number[], patch: { stars?: number; rejected?: boolean }) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/videos/rating`, {
      method: 'POST',
      body: JSON.stringify({ video_ids, ...patch }),
    }),
  deleteVideo: (pid: string, vid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/videos/${vid}`, { method: 'DELETE' }),
  excluded: (pid: string) => req<ExcludedFile[]>(`/api/projects/${pid}/excluded`),
  restoreExcluded: (pid: string, eid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/excluded/${eid}`, { method: 'DELETE' }),
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

  people: (pid: string) => req<PeopleResponse>(`/api/projects/${pid}/people`),
  detectFaces: (pid: string, video_ids?: number[], force = false) =>
    req<{ queued: number }>(`/api/projects/${pid}/faces/detect`, {
      method: 'POST',
      body: JSON.stringify({ video_ids: video_ids ?? null, force }),
    }),
  reclusterPeople: (pid: string) =>
    req<{ queued: boolean }>(`/api/projects/${pid}/people/recluster`, { method: 'POST' }),
  updatePerson: (pid: string, personId: number, patch: { name?: string; cover_face_id?: number; hidden?: boolean }) =>
    req<Person>(`/api/projects/${pid}/people/${personId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  mergePerson: (pid: string, personId: number, intoId: number) =>
    req<Person>(`/api/projects/${pid}/people/${personId}/merge`, {
      method: 'POST',
      body: JSON.stringify({ into_id: intoId }),
    }),
  deletePerson: (pid: string, personId: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/people/${personId}`, { method: 'DELETE' }),
  personFaces: (pid: string, personId: number) =>
    req<FaceInfo[]>(`/api/projects/${pid}/people/${personId}/faces`),
  videoFaces: (pid: string, vid: number) =>
    req<FaceInfo[]>(`/api/projects/${pid}/videos/${vid}/faces`),
  updateFace: (pid: string, faceId: number, patch: { person_id?: number | null; ignored?: boolean }) =>
    req<FaceInfo>(`/api/projects/${pid}/faces/${faceId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  song: (pid: string) => req<SongInfo>(`/api/projects/${pid}/song`),
  songPeaks: (pid: string) => req<{ peaks: [number, number][] }>(`/api/projects/${pid}/song/peaks`),
  videoPeaks: (pid: string, vid: number) =>
    req<{ peaks: [number, number][] }>(`/api/projects/${pid}/videos/${vid}/audio-peaks`),
  songAudio: (pid: string, patch: { muted?: boolean; volume?: number }) =>
    req<{ muted: boolean; volume: number }>(`/api/projects/${pid}/song/audio`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  songReanalyze: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/reanalyze`, { method: 'POST' }),
  songLabel: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/label`, { method: 'POST' }),
  songTranscribe: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/song/lyrics`, { method: 'POST' }),
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

  compose: (pid: string, instructions: string) =>
    req<{ job_id: number }>(`/api/projects/${pid}/compose`, {
      method: 'POST',
      body: JSON.stringify({ instructions }),
    }),

  timeline: (pid: string) =>
    req<{ tracks: Track[]; can_undo: boolean; can_redo: boolean }>(`/api/projects/${pid}/timeline`),
  addTrack: (pid: string) => req<Track>(`/api/projects/${pid}/tracks`, { method: 'POST' }),
  removeTrack: (pid: string, tid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/tracks/${tid}`, { method: 'DELETE' }),
  trackAudio: (pid: string, tid: number, patch: { muted?: boolean; volume?: number }) =>
    req<{ id: number; audio_muted: boolean; audio_volume: number }>(
      `/api/projects/${pid}/tracks/${tid}/audio`,
      { method: 'PATCH', body: JSON.stringify(patch) },
    ),
  addClip: (
    pid: string,
    clip: { track_id: number; video_id: number; timeline_start: number; source_in: number; source_out: number; speed?: number },
  ) => req<{ id: number }>(`/api/projects/${pid}/clips`, { method: 'POST', body: JSON.stringify(clip) }),
  updateClip: (
    pid: string,
    cid: number,
    patch: { timeline_start?: number; track_id?: number; source_in?: number; source_out?: number; speed?: number },
  ) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/clips/${cid}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),
  splitClip: (pid: string, cid: number, at: number) =>
    req<{ id: number }>(`/api/projects/${pid}/clips/${cid}/split`, {
      method: 'POST',
      body: JSON.stringify({ at }),
    }),
  deleteClip: (pid: string, cid: number) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/clips/${cid}`, { method: 'DELETE' }),
  undoTimeline: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/timeline/undo`, { method: 'POST' }),
  redoTimeline: (pid: string) =>
    req<{ ok: boolean }>(`/api/projects/${pid}/timeline/redo`, { method: 'POST' }),
}

export const media = {
  video: (pid: string, vid: number) => `/media/${pid}/video/${vid}`,
  preview: (pid: string, vid: number) => `/media/${pid}/preview/${vid}`,
  thumb: (pid: string, vid: number) => `/media/${pid}/thumb/${vid}`,
  filmstrip: (pid: string, vid: number) => `/media/${pid}/filmstrip/${vid}`,
  face: (pid: string, fid: number) => `/media/${pid}/face/${fid}`,
  faceFrame: (pid: string, fid: number) => `/media/${pid}/face/${fid}/frame`,
  song: (pid: string) => `/media/${pid}/song`,
}

export function fmtTime(s: number): string {
  if (!isFinite(s)) return '0:00'
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`
}

export function fmtBytes(n: number): string {
  if (!n) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}
