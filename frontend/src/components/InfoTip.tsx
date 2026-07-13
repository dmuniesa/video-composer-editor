import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

const POP_W = 280

/** Small "?" button that toggles a contextual help popover — keeps
 *  explanatory text out of the layout until the user asks for it.
 *  The popover is position:fixed so scroll containers can't clip it. */
export default function InfoTip({ children }: { children: ReactNode }) {
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null)
  const ref = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!pos) return
    const close = () => setPos(null)
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
    }
  }, [pos])

  const toggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (pos) {
      setPos(null)
      return
    }
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setPos({
      x: Math.max(8, Math.min(r.left, window.innerWidth - POP_W - 12)),
      y: r.bottom + 6,
    })
  }

  return (
    <span className="infotip" ref={ref}>
      <button type="button" className="infotip-btn" title="help" onClick={toggle}>
        ?
      </button>
      {pos && (
        <div className="infotip-pop" style={{ left: pos.x, top: pos.y }}>
          {children}
        </div>
      )}
    </span>
  )
}
