import { useEffect, useRef } from 'react'

interface CVDChartProps {
  data: { time: string; cvd: number; slope: number }[]
  height?: number
  width?: number
}

export function CVDChart({ data, height = 150, width = 600 }: CVDChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length === 0) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, width, height)

    const padding = 30
    const chartWidth = width - padding * 2
    const chartHeight = height - padding * 2

    const minCVD = Math.min(...data.map((d) => d.cvd))
    const maxCVD = Math.max(...data.map((d) => d.cvd))
    const range = maxCVD - minCVD || 1
    const zeroY = padding + ((maxCVD) / range) * chartHeight

    // Zero line
    ctx.strokeStyle = '#555'
    ctx.lineWidth = 0.5
    ctx.beginPath()
    ctx.moveTo(padding, zeroY)
    ctx.lineTo(width - padding, zeroY)
    ctx.stroke()

    // CVD line
    ctx.strokeStyle = '#3b82f6'
    ctx.lineWidth = 1.5
    ctx.beginPath()

    data.forEach((d, i) => {
      const x = padding + (i / (data.length - 1)) * chartWidth
      const y = padding + ((maxCVD - d.cvd) / range) * chartHeight

      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()

    // Slope indicator (last point)
    if (data.length > 1) {
      const last = data[data.length - 1]
      const slopeColor = last.slope > 0 ? '#22c55e' : '#ef4444'
      ctx.fillStyle = slopeColor
      ctx.font = '10px monospace'
      ctx.fillText(`Slope: ${last.slope.toFixed(1)}`, padding, 12)
    }

    // Labels
    ctx.fillStyle = '#888'
    ctx.font = '9px monospace'
    ctx.fillText(`Max: ${maxCVD.toFixed(0)}`, padding, 12)
    ctx.fillText(`Min: ${minCVD.toFixed(0)}`, padding, height - 4)
  }, [data, height, width])

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="rounded border border-gray-700 bg-trade-dark"
    />
  )
}
