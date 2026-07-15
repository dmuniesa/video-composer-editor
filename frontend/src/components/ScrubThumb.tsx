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
 *  (mounted only during hover) seeks there live.
 *
 *  Scrubs the low-res preview proxy (dense keyframes, cheap to decode) and
 *  coalesces seeks: at most one in flight, the latest target wins. Assigning
 *  currentTime on every mousemove piles up async seeks and stutters. */
export default function ScrubThumb({ pid, videoId, duration, children }: Props) {
  const [hover, setHover] = useState(false)
  const [frac, setFrac] = useState(0)
  const fracRef = useRef(0)
  const videoRef = useRef<HTMLVideoElement>(null)
  const seekingRef = useRef(false)
  const pendingRef = useRef<number | null>(null)

  const seek = (f: number) => {
    const v = videoRef.current
    if (!v || v.readyState < 1 || !duration) return
    const t = f * duration
    if (seekingRef.current) {
      pendingRef.current = t
      return
    }
    seekingRef.current = true
    // fastSeek lands on the nearest keyframe (~0.5s apart in the preview),
    // close enough for a thumbnail and much faster than a precise seek
    if (typeof v.fastSeek === 'function') v.fastSeek(t)
    else v.currentTime = t
  }

  const onSeeked = () => {
    seekingRef.current = false
    if (pendingRef.current != null) {
      const t = pendingRef.current
      pendingRef.current = null
      seek(duration ? t / duration : 0)
    }
  }

  const onMove = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const f = Math.min(0.999, Math.max(0, (e.clientX - rect.left) / rect.width))
    fracRef.current = f
    setFrac(f)
    seek(f)
  }

  const onLeave = () => {
    setHover(false)
    seekingRef.current = false
    pendingRef.current = null
  }

  return (
    <div
      className="thumb"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={onLeave}
      onMouseMove={onMove}
    >
      <img src={media.thumb(pid, videoId)} loading="lazy" alt="" draggable={false} />
      {hover && duration > 0 && (
        <>
          <video
            ref={videoRef}
            className="scrub-video"
            src={media.preview(pid, videoId)}
            muted
            playsInline
            preload="auto"
            onLoadedMetadata={() => seek(fracRef.current)}
            onSeeked={onSeeked}
          />
          <div className="scrub-line" style={{ left: `${frac * 100}%` }} />
          <span className="scrub-time">{fmtTime(frac * duration)}</span>
        </>
      )}
      {children}
    </div>
  )
}
