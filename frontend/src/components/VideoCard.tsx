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
  // Plain click on the thumbnail/title/description opens the detail;
  // hold Ctrl/Cmd/Shift to (multi-)select instead of opening.
  const activate = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (e.ctrlKey || e.metaKey || e.shiftKey) onSelect(e)
    else onOpen()
  }
  return (
    <div
      className={`video-card ${selected ? 'selected' : ''} ${video.rejected ? 'rejected' : ''}`}
      onClick={onSelect}
    >
      <div className="thumb-hit" onClick={activate}>
        <ScrubThumb pid={pid} videoId={video.id} duration={video.duration}>
          <span className="duration">{fmtTime(video.duration)}</span>
          {video.fps > 0 && <span className="fps">{Math.round(video.fps)} fps</span>}
          {video.width > 0 && <span className="dims">{video.width}×{video.height}</span>}
          {video.status !== 'ready' && <span className="status-chip">{video.status}</span>}
          {video.rejected && <span className="status-chip" style={{ top: 26, color: 'var(--danger)' }}>rejected</span>}
        </ScrubThumb>
      </div>
      <div className="body">
        <div className="name" title={video.rel_path} onClick={activate}>{video.filename}</div>
        <div className="desc" onClick={activate}>{video.error ? <span className="error-text">{video.error}</span> : video.description || '—'}</div>
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
