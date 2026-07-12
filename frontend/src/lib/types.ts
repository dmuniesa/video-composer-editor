export interface ProjectInfo {
  id: string
  name: string
  video_dir: string
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
  lyrics: {
    enabled: boolean
    whisper_model: string
    language: string
    min_instrumental_gap: number
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

export interface Video {
  id: number
  rel_path: string
  filename: string
  duration: number
  fps: number
  width: number
  height: number
  codec: string
  size: number
  shot_at: string | null
  status: string
  error: string | null
  has_proxy: boolean
  frame_count: number
  description: string
  ai_score: number | null
  hashtags: string[]
  stars: number
  rejected: boolean
  ranges: VideoRange[]
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
}
