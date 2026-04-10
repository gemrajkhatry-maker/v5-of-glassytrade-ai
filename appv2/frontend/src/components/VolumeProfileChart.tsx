import { useEffect, useRef } from 'react'

interface VolumeProfileProps {
  profile: { price: number; volume: number }[]
  poc: number
  vah: number
  val: number
  currentPrice: number
  height?: number
  width?: number
}

export function VolumeProfileChart({
  profile,
  poc,
  vah,
  val,
  currentPrice,
  height = 400,
  width = 200,
}: VolumeProfileProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || profile.length === 0) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, width, height)

    const maxVol = Math.max(...profile.map((p) => p.volume))
    const minPrice = Math.min(...profile.map((p) => p.price))
    const maxPrice = Math.max(...profile.map((p) => p.price))
    const priceRange = maxPrice - minPrice || 1

    const barHeight = height / profile.length
    const padding = 4

    // Draw bars
    profile.forEach((level, i) => {
      const y = height - (i + 1) * barHeight
      const barWidth = (level.volume / maxVol) * (width - padding * 2)
      const barColor =
        level.price > poc ? 'rgba(239, 68, 68, 0.6)' : 'rgba(34, 197, 94, 0.6)'

      ctx.fillStyle = barColor
      ctx.fillRect(padding, y, barWidth, barHeight - 1)
    })

    // Draw VAH/VAL lines
    const drawLevel = (price: number, color: string, label: string) => {
      const y = height - ((price - minPrice) / priceRange) * height
      ctx.strokeStyle = color
      ctx.lineWidth = 1
      ctx.setLineDash([4, 2])
      ctx.beginPath()
      ctx.moveTo(0, y)
      ctx.lineTo(width, y)
      ctx.stroke()
      ctx.setLineDash([])

      ctx.fillStyle = color
      ctx.font = '10px monospace'
      ctx.fillText(label, 2, y - 2)
    }

    drawLevel(vah, '#eab308', 'VAH')
    drawLevel(val, '#eab308', 'VAL')
    drawLevel(poc, '#a855f7', 'POC')

    // Current price marker
    const priceY = height - ((currentPrice - minPrice) / priceRange) * height
    ctx.fillStyle = '#3b82f6'
    ctx.beginPath()
    ctx.moveTo(0, priceY - 4)
    ctx.lineTo(8, priceY)
    ctx.lineTo(0, priceY + 4)
    ctx.fill()
  }, [profile, poc, vah, val, currentPrice, height, width])

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      className="rounded border border-gray-700 bg-trade-dark"
    />
  )
}
