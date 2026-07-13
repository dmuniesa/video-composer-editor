import { fmtTime } from '../lib/api'
import type { Video } from '../lib/types'
import ScrubThumb from './ScrubThumb'
import StarRating from './StarRating'

interface Props {
  pid: string
  video: Video
  selected: boolean
  onSelect: (e: React.MouseEvent) => void
  onOpen: () => void
  onRate: (stars: number) => void
  onTagClick?: (tag: string) => void
  activeTag?: string
}

export default function VideoCard({ pid, video, selected, onSelect, onOpen, onRate, onTagClick, activeTag }: Props) {
  return (
    <div
      className={`video-card ${selected ? 'selected' : ''} ${video.rejected ? 'rejected' : ''}`}
      onClick={onSelect}
      onDoubleClick={onOpen}
    >
      <ScrubThumb pid={pid} videoId={video.id} duration={video.duration}>
        <span className="duration">{fmtTime(video.duration)}</span>
        {video.fps > 0 && <span className="fps">{Math.round(video.fps)} fps</span>}
        {video.width > 0 && <span className="dims">{video.width}×{video.height}</span>}
        {video.status !== 'ready' && <span className="status-chip">{video.status}</span>}
        {video.rejected && <span className="status-chip" style={{ top: 26, color: 'var(--danger)' }}>rejected</span>}
      </ScrubThumb>
      <div className="body">
        <div className="name" title={video.rel_path}>{video.filename}</div>
        <div className="desc">{video.error ? <span className="error-text">{video.error}</span> : video.description || '—'}</div>
        <div className="tag-row">
          {video.hashtags.slice(0, 5).map((t) => (
            <span
              key={t}
              className={`tag ${activeTag === t ? 'active' : ''}`}
              onClick={(e) => {
                e.stopPropagation()
                onTagClick?.(t)
              }}
            >
              #{t}
            </span>
          ))}
        </div>
        <div className="card-footer">
          <StarRating stars={video.stars} onChange={onRate} />
          <span className="ai-score">{video.ai_score != null && <>AI <b>{video.ai_score}</b>/10</>}</span>
        </div>
      </div>
    </div>
  )
}
