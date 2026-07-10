export interface ProjectInfo {
  id: string
  name: string
  video_dir: string
  song_path: string | null
  song_status: string | null
  video_count: number
  videos_by_status: Record<string, number>
  agy_available: boolean
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
}

export interface SongInfo {
  path: string
  duration: number
  bpm: number | null
  beats: number[]
  downbeats: number[]
  status: string
  error: string | null
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
