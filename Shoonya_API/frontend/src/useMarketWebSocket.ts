import { useCallback, useEffect, useRef, useState } from 'react'

export interface Tick {
  t: string
  tk: string
  e?: string
  lp?: string
  oi?: string
  v?: string
  h?: string
  l?: string
  c?: string
  ap?: string
  pc?: string
  poi?: string
  toi?: string
  bq1?: string
  bp1?: string
  sq1?: string
  sp1?: string
}

export type PricesMap = Record<string, Tick>

export interface SubscribeToken {
  exch: string
  token: string
}

const WS_URL = 'ws://localhost:8000/ws/market-data'
const MAX_BACKOFF_MS = 22_000

export function useMarketWebSocket() {
  const [prices, setPrices] = useState<PricesMap>({})
  const [wsReady, setWsReady] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const attemptRef = useRef(0)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const unmountedRef = useRef(false)

  useEffect(() => {
    unmountedRef.current = false

    function connect() {
      if (unmountedRef.current) return
      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        if (unmountedRef.current) { ws.close(); return }
        attemptRef.current = 0
        setWsReady(true)
      }

      ws.onclose = () => {
        setWsReady(false)
        if (unmountedRef.current) return
        const delay = Math.min(1_000 * 2 ** attemptRef.current, MAX_BACKOFF_MS)
        attemptRef.current++
        timerRef.current = setTimeout(connect, delay)
      }

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as Tick
          if ((data.t === 'tf' || data.t === 'tk') && data.tk) {
            setPrices(prev => ({ ...prev, [data.tk]: { ...prev[data.tk], ...data } }))
          }
        } catch {
          // ignore malformed messages
        }
      }
    }

    connect()

    return () => {
      unmountedRef.current = true
      if (timerRef.current) clearTimeout(timerRef.current)
      if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.close()
    }
  }, [])

  const subscribe = useCallback((tokens: SubscribeToken[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'subscribe', type: 'touchline', tokens }))
    }
  }, [])

  const unsubscribe = useCallback((tokens: SubscribeToken[]) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ action: 'unsubscribe', type: 'touchline', tokens }))
    }
  }, [])

  return { prices, subscribe, unsubscribe, wsReady }
}
