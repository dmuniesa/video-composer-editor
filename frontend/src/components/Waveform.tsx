import { useEffect, useRef } from 'react'

interface Props {
  peaks: [number, number][]
  width: number
  height: number
  color?: string
  /** Linear gain applied to the peaks for a purely visual amplitude hint
   * (e.g. a per-clip dB offset). Peaks are clamped to ±1 so a large boost
   * "clips" against the top/bottom like real audio. Defaults to 1 (no change). */
  gain?: number
}

export default function Waveform({ peaks, width, height, color = '#4f8cff', gain = 1 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas || peaks.length === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = width * dpr
    canvas.height = height * dpr
    const ctx = canvas.getContext('2d')!
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, width, height)
    ctx.fillStyle = color
    const mid = height / 2
    const bar = width / peaks.length
    for (let i = 0; i < peaks.length; i++) {
      let [min, max] = peaks[i]
      if (gain !== 1) {
        min = Math.max(-1, min * gain)
        max = Math.min(1, max * gain)
      }
      const y1 = mid + min * mid
      const y2 = mid + max * mid
      ctx.fillRect(i * bar, Math.min(y1, y2), Math.max(bar - 0.5, 0.5), Math.max(Math.abs(y2 - y1), 1))
    }
  }, [peaks, width, height, color, gain])

  return <canvas ref={ref} style={{ width, height, display: 'block' }} />
}
