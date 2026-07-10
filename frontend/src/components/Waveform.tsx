import { useEffect, useRef } from 'react'

interface Props {
  peaks: [number, number][]
  width: number
  height: number
  color?: string
}

export default function Waveform({ peaks, width, height, color = '#4f8cff' }: Props) {
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
      const [min, max] = peaks[i]
      const y1 = mid + min * mid
      const y2 = mid + max * mid
      ctx.fillRect(i * bar, Math.min(y1, y2), Math.max(bar - 0.5, 0.5), Math.max(Math.abs(y2 - y1), 1))
    }
  }, [peaks, width, height, color])

  return <canvas ref={ref} style={{ width, height, display: 'block' }} />
}
