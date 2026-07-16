export interface Source {
  id: number
  path: string
  label: string
  online: boolean
  video_count: number
}

export interface ExcludedFile {
  id: number
  source_id: number | null
  rel_path: string
  filename: string
  excluded_at: string | null
}

export interface ProjectInfo {
  id: string
  name: string
  video_dir: string
  sources: Source[]
  composition_fps: number
  composition_width: number
  composition_height: number
  song_path: string | null
  song_status: string | null
  video_count: number
  videos_by_status: Record<string, number>
  ai_available: boolean
  ai_provider: string | null
  composer_provider: string
  composer_available: boolean
}

export interface AppSettings {
  frames: {
    min_count: number
    max_count: number
    seconds_per_frame: number
    width: number
    jpeg_quality: number
    filmstrip_tiles: number
    proxy_height: number
    preview_height: number
  }
  ai: {
    provider: string
    agy_cmd: string
    openai_base_url: string
    openai_api_key: string
    openai_model: string
    timeout_s: number
  }
  composer: {
    provider: string
  }
  /** Optional AI-analysis aspects; a disabled one is neither requested from
   *  the AI nor shown/used anywhere (stored values are kept). */
  analysis: {
    mood: boolean
    energy: boolean
    scene: boolean
    people_in_prompt: boolean
  }
  lyrics: {
    enabled: boolean
    provider: string
    whisper_model: string
    language: string
    min_instrumental_gap: number
  }
  faces: {
    model_pack: string
    frame_interval_s: number
    max_frames: number
  }
  debug_logging: boolean
  ai_status?: { available: boolean; provider: string | null }
}

export interface VideoRange {
  id: number
  t_in: number
  t_out: number
  label: string
}

/** Curated ffprobe container tags. Fields present only when the file carried
 *  them; `tags` holds any other raw tags. Not shown on thumbnails. */
export interface VideoMeta {
  make?: string
  model?: string
  lens?: string
  software?: string
  location?: string
  tags?: Record<string, string>
}

export interface Video {
  id: number
  rel_path: string
  source_id: number | null
  source_label: string
  filename: string
  duration: number
  fps: number
  width: number
  height: number
  codec: string
  size: number
  shot_at: string | null
  meta: VideoMeta
  status: string
  error: string | null
  has_proxy: boolean
  frame_count: number
  faces_status: string
  people: PersonRef[]
  description: string
  ai_score: number | null
  hashtags: string[]
  mood: string[]
  energy: 'low' | 'medium' | 'high' | null
  scene: string | null
  time_of_day: string | null
  shot_type: string | null
  stars: number
  rejected: boolean
  ranges: VideoRange[]
}

/** Named person appearing in a video (Review chips / filters). */
export interface PersonRef {
  id: number
  name: string
}

export interface Person {
  id: number
  name: string
  cover_face_id: number | null
  /** Not interesting: kept (still absorbs new faces) but out of lists/chips. */
  hidden: boolean
  face_count: number
  videos: { id: number; filename: string }[]
}

export interface PeopleResponse {
  available: boolean
  reason: string | null
  persons: Person[]
}

export interface FaceInfo {
  id: number
  video_id: number
  filename: string
  frame_index: number
  t: number
  /** bbox normalized 0-1 relative to the sampled frame */
  x: number
  y: number
  w: number
  h: number
  det_score: number
  similarity: number | null
  person_id: number | null
  ignored: boolean
}

export interface SongSection {
  id: number
  start: number
  end: number
  label: string
  source: string
  energy: number
  vocal_ratio: number | null
}

export interface LyricLine {
  start: number
  end: number
  text: string
}

export interface TimeRange {
  start: number
  end: number
}

export interface SongLyrics {
  status: string
  error: string | null
  language: string
  model: string
  segments: LyricLine[]
  vocal_ranges: TimeRange[]
  instrumental_ranges: TimeRange[]
}

export interface SongInfo {
  path: string
  duration: number
  bpm: number | null
  beats: number[]
  downbeats: number[]
  status: string
  error: string | null
  lyrics: SongLyrics | null
  lyrics_enabled: boolean
  sections: SongSection[]
}

export interface TimelineClip {
  id: number
  video_id: number
  timeline_start: number
  source_in: number
  source_out: number
  speed: number
  duration: number
  placed_by: string
}

export interface Track {
  id: number
  index: number
  name: string
  clips: TimelineClip[]
}

export interface JobInfo {
  id: number
  kind: string
  label: string
  status: string
  progress: number
  message: string
  video_id: number | null
}

export interface FsListing {
  path: string
  parent: string | null
  dirs: string[]
  videos: string[]
  audios: string[]
}

export interface LogRecord {
  seq: number
  time: number
  level: string
  logger: string
  message: string
  project_id?: string | null
}
