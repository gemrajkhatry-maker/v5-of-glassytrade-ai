import { useEffect, useRef } from 'react'

interface VWAPChartProps {
  data: { time: string; price: number; vwap: number; upper1: number; lower1: number; upper2: number; lower2: number }[]
  height?: number
  width?: number
}

export function VWAPChart({ data, height = 300, width = 800 }: VWAPChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length < 2) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, width, height)

    const padding = { top: 20, right: 20, bottom: 30, left: 60 }
    const chartW = width - padding.left - padding.right
    const chartH = height - padding.top - padding.bottom

    // Find price range including bands
    const allValues = data.flatMap((d) => [d.price, d.vwap, d.upper2, d.lower2])
    const minP = Math.min(...allValues)
    const maxP = Math.max(...allValues)
    const range = maxP - minP || 1

    const toX = (i: number) => padding.left + (i / (data.length - 1)) * chartW
    const toY = (v: number) => padding.top + ((maxP - v) / range) * chartH

    // Draw σ bands
    const drawBand = (upperKey: string, lowerKey: string, color: string) => {
      ctx.fillStyle = color
      ctx.beginPath()
      data.forEach((d, i) => {
        const x = toX(i)
        const y = toY((d as any)[upperKey])
        if (i === 0) ctx.moveTo(x, y)
        else ctx.lineTo(x, y)
      })
      for (let i = data.length - 1; i >= 0; i--) {
        const x = toX(i)
        const y = toY((data[i] as any)[lowerKey])
        ctx.lineTo(x, y)
      }
      ctx.closePath()
      ctx.fill()
    }

    // 2σ band
    drawBand('upper2', 'lower2', 'rgba(139, 92, 246, 0.1)')
    // 1σ band
    drawBand('upper1', 'lower1', 'rgba(59, 130, 246, 0.15)')

    // VWAP line
    ctx.strokeStyle = '#a855f7'
    ctx.lineWidth = 2
    ctx.beginPath()
    data.forEach((d, i) => {
      const x = toX(i)
      const y = toY(d.vwap)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()

    // Price line
    ctx.strokeStyle = '#e0e0e0'
    ctx.lineWidth = 1
    ctx.beginPath()
    data.forEach((d, i) => {
      const x = toX(i)
      const y = toY(d.price)
      if (i === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.stroke()

    // Price axis labels
    ctx.fillStyle = '#888'
    ctx.font = '10px monospace'
    const steps = 5
    for (let i = 0; i <= steps; i++) {
      const value = minP + (range * i) / steps
      const y = toY(value)
      ctx.fillText(value.toFixed(1), 4, y + 3)
      ctx.strokeStyle = '#333'
      ctx.lineWidth = 0.5
      ctx.beginPath()
      ctx.moveTo(padding.left, y)
      ctx.lineTo(width - padding.right, y)
      ctx.stroke()
    }

    // Legend
    const legendY = padding.top + 5
    ctx.fillStyle = '#e0e0e0'
    ctx.fillRect(width - 120, legendY, 12, 2)
    ctx.fillText('Price', width - 104, legendY + 4)
    ctx.fillStyle = '#a855f7'
    ctx.fillRect(width - 120, legendY + 14, 12, 2)
    ctx.fillText('VWAP', width - 104, legendY + 18)
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
