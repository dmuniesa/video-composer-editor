import { useRef, useState } from 'react'
import { media, fmtTime } from '../lib/api'

interface Props {
  pid: string
  videoId: number
  duration: number
  /** overlays rendered on top (duration badge, status chips...) */
  children?: React.ReactNode
}

/** Premiere/FCP-style hover scrub: while the pointer is over the thumbnail,
 *  its horizontal position maps to a time in the clip and a muted <video>
 *  (mounted only during hover) seeks there live. */
export default function ScrubThumb({ pid, videoId, duration, children }: Props) {
  const [hover, setHover] = useState(false)
  const [frac, setFrac] = useState(0)
  const fracRef = useRef(0)
  const videoRef = useRef<HTMLVideoElement>(null)

  const seek = (f: number) => {
    const v = videoRef.current
    if (v && v.readyState >= 1 && duration) v.currentTime = f * duration
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const f = Math.min(0.999, Math.max(0, (e.clientX - rect.left) / rect.width))
    fracRef.current = f
    setFrac(f)
    seek(f)
  }

  return (
    <div
      className="thumb"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onMouseMove={onMove}
    >
      <img src={media.thumb(pid, videoId)} loading="lazy" alt="" draggable={false} />
      {hover && duration > 0 && (
        <>
          <video
            ref={videoRef}
            className="scrub-video"
            src={media.video(pid, videoId)}
            muted
            playsInline
            preload="auto"
            onLoadedMetadata={() => seek(fracRef.current)}
          />
          <div className="scrub-line" style={{ left: `${frac * 100}%` }} />
          <span className="scrub-time">{fmtTime(frac * duration)}</span>
        </>
      )}
      {children}
    </div>
  )
}
