import { useCallback, useRef } from 'react'

/**
 * Routes the preview <video> through a Web Audio GainNode so the montage preview
 * can apply a per-clip audio gain — including boosts above 0 dB, which the
 * HTMLMediaElement.volume property (clamped to 0–1) cannot represent.
 *
 * One AudioContext + GainNode is kept per page instance (in refs, surviving the
 * preview popup unmount/remount). The MediaElementAudioSourceNode is created
 * exactly once per <video> element (calling createMediaElementSource twice on
 * the same element throws InvalidStateError) and tracked in a WeakMap, so a
 * remounted element gets a fresh source and stale ones are garbage-collected.
 *
 * Media is served same-origin (/media/...), so it is not CORS-tainted and Web
 * Audio can read it. The AudioContext starts suspended until resume() is called
 * from a user gesture (the play click).
 */
export function usePreviewGain() {
  const ctxRef = useRef<AudioContext | null>(null)
  const gainRef = useRef<GainNode | null>(null)
  const sourcesRef = useRef<WeakMap<HTMLMediaElement, MediaElementAudioSourceNode>>(new WeakMap())

  const ensureCtx = useCallback((): AudioContext | null => {
    if (ctxRef.current) return ctxRef.current
    const Ctor: typeof AudioContext | undefined =
      window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
    if (!Ctor) return null
    const ctx = new Ctor()
    const gain = ctx.createGain()
    gain.gain.value = 1
    gain.connect(ctx.destination)
    ctxRef.current = ctx
    gainRef.current = gain
    return ctx
  }, [])

  /** Wire a <video> element into the graph (idempotent per element). */
  const bind = useCallback(
    (el: HTMLVideoElement | null) => {
      if (!el) return
      const ctx = ensureCtx()
      if (!ctx || !gainRef.current) return
      if (sourcesRef.current.has(el)) return
      try {
        const src = ctx.createMediaElementSource(el)
        src.connect(gainRef.current)
        sourcesRef.current.set(el, src)
      } catch {
        // Already bound (defensive — the WeakMap guard should prevent this).
      }
    },
    [ensureCtx],
  )

  /** Set the preview gain as a linear multiplier (0 = silent, 1 = unity, >1 = boost). */
  const setGain = useCallback((linear: number) => {
    if (gainRef.current && Number.isFinite(linear) && linear >= 0) {
      gainRef.current.gain.value = linear
    }
  }, [])

  /** Resume the AudioContext from within a user gesture (e.g. the play click). */
  const resume = useCallback(() => {
    const ctx = ensureCtx()
    if (ctx && ctx.state === 'suspended') void ctx.resume()
  }, [ensureCtx])

  return { bind, setGain, resume }
}
