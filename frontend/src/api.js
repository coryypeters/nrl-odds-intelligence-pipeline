import { useEffect, useRef, useState, useCallback } from 'react'

// Resolve API/WS base URLs. In Docker we publish the API on host port 8000,
// so from the browser it's always localhost:8000 regardless of compose names.
// Override via Vite env vars if deploying behind a different host.
const API_BASE = import.meta.env.VITE_API_BASE || `http://${location.hostname}:8000`
const WS_BASE  = import.meta.env.VITE_WS_BASE  || `ws://${location.hostname}:8000`

export async function fetchEvents(kind) {
  const url = new URL(`${API_BASE}/api/events`)
  if (kind && kind !== 'all') url.searchParams.set('kind', kind)
  url.searchParams.set('limit', '100')
  const res = await fetch(url)
  if (!res.ok) throw new Error(`events ${res.status}`)
  return (await res.json()).events
}

export async function fetchOdds() {
  const res = await fetch(`${API_BASE}/api/odds`)
  if (!res.ok) throw new Error(`odds ${res.status}`)
  return (await res.json()).events
}

export async function fetchMatch(eventId) {
  const res = await fetch(`${API_BASE}/api/match/${encodeURIComponent(eventId)}`)
  if (!res.ok) throw new Error(`match ${res.status}`)
  return await res.json()
}

/**
 * Live event stream over WebSocket with auto-reconnect.
 * Returns { status, last } where status is 'connecting'|'live'|'reconnecting'
 * and last is the most recent parsed event (drives the feed prepend).
 */
export function useEventStream() {
  const [status, setStatus] = useState('connecting')
  const [last, setLast] = useState(null)
  const wsRef = useRef(null)
  const retryRef = useRef(null)

  const connect = useCallback(() => {
    const ws = new WebSocket(`${WS_BASE}/ws/events`)
    wsRef.current = ws

    ws.onopen = () => setStatus('live')
    ws.onmessage = (e) => {
      try { setLast(JSON.parse(e.data)) } catch { /* ignore malformed */ }
    }
    ws.onclose = () => {
      setStatus('reconnecting')
      retryRef.current = setTimeout(connect, 2000)  // backoff retry
    }
    ws.onerror = () => ws.close()
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(retryRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { status, last }
}
