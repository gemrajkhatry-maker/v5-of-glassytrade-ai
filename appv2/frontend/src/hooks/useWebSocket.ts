/// <reference types="vite/client" />
import { useState, useEffect, useCallback } from 'react'

const BACKEND_URL = (import.meta as any).env?.VITE_BACKEND_URL || 'http://localhost:8001'

export function useWebSocket() {
  const [connected, setConnected] = useState(false)
  const [data, setData] = useState<Record<string, unknown>>({})
  const [ws, setWs] = useState<WebSocket | null>(null)

  const connect = useCallback(() => {
    const url = `ws://${window.location.hostname}:8001/api/v2/ws`
    const socket = new WebSocket(url)

    socket.onopen = () => {
      console.log('WebSocket connected')
      setConnected(true)
    }

    socket.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data)
        setData((prev) => ({ ...prev, ...parsed }))
      } catch {
        // Non-JSON message
        setData((prev) => ({ ...prev, raw: event.data }))
      }
    }

    socket.onclose = () => {
      console.log('WebSocket disconnected')
      setConnected(false)
      // Auto-reconnect after 3s
      setTimeout(connect, 3000)
    }

    socket.onerror = (err) => {
      console.error('WebSocket error:', err)
    }

    setWs(socket)
  }, [])

  useEffect(() => {
    connect()
    return () => {
      ws?.close()
    }
  }, [connect])

  const send = useCallback(
    (message: Record<string, unknown>) => {
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(message))
      }
    },
    [ws]
  )

  return { connected, data, send, reconnect: connect }
}

export async function fetchHealth() {
  const res = await fetch(`${BACKEND_URL}/api/v2/health`)
  return res.json()
}

export async function fetchSymbols() {
  const res = await fetch(`${BACKEND_URL}/api/v2/market/symbols`)
  return res.json()
}

export async function fetchSignals() {
  const res = await fetch(`${BACKEND_URL}/api/v2/signals/active`)
  return res.json()
}

export async function fetchPositions() {
  const res = await fetch(`${BACKEND_URL}/api/v2/positions/open`)
  return res.json()
}
