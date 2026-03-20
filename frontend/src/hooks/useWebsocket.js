import { useState, useEffect, useRef, useCallback } from 'react'

export function useWebsocket(url) {
  const [messages, setMessages] = useState([])
  const [isConnected, setIsConnected] = useState(false)
  const ws = useRef(null)
  const reconnectTimeout = useRef(null)
  const backoff = useRef({ delay: 1000, max: 10000 })
  const subscriptions = useRef(new Set())
  const mountedRef = useRef(true)
  const shouldReconnectRef = useRef(true)
  const connectInitTimeout = useRef(null)

  const scheduleReconnect = useCallback(() => {
    if (!mountedRef.current || !shouldReconnectRef.current) return
    clearTimeout(reconnectTimeout.current)
    const nextDelay = backoff.current.delay
    reconnectTimeout.current = setTimeout(() => {
      if (mountedRef.current && shouldReconnectRef.current) {
        backoff.current.delay = Math.min(Math.round(backoff.current.delay * 1.5), backoff.current.max)
        connect()
      }
    }, nextDelay)
  }, [])

  const connect = useCallback(() => {
    if (!url || typeof url !== 'string') return
    if (ws.current?.readyState === WebSocket.OPEN || ws.current?.readyState === WebSocket.CONNECTING) return

    let socket = null

    try {
      socket = new WebSocket(url)
      ws.current = socket
    } catch (e) {
      console.error('WS: Failed to create WebSocket:', e)
      scheduleReconnect()
      return
    }

    socket.onopen = () => {
      if (!mountedRef.current || ws.current !== socket) return
      console.log('WS connected to', url)
      setIsConnected(true)
      backoff.current.delay = 1000 // reset backoff

      // Resubscribe if we had active subs
      if (subscriptions.current.size > 0) {
        try {
          socket.send(JSON.stringify({
            action: 'subscribe',
            symbols: Array.from(subscriptions.current)
          }))
        } catch (err) {
          console.error('WS: Failed to send resubscribe payload:', err)
        }
      }
    }

    socket.onmessage = (e) => {
      if (!mountedRef.current || ws.current !== socket) return
      try {
        const msg = JSON.parse(e.data)
        if (!msg || typeof msg !== 'object') return

        // Respond to server heartbeat
        if (msg.type === 'heartbeat') {
          if (socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ action: 'pong' }))
          }
          return // Don't add heartbeats to message queue
        }

        if (msg.type === 'tick') {
          console.debug(`[WS] Tick: ${msg.symbol} LTP=${msg.ltp}`)
        } else if (msg.type !== 'status' && msg.type !== 'subscribed') {
          console.debug(`[WS] ${msg.type}`, msg.symbol || '')
        }

        setMessages(prev => {
          // Keep only the latest 50 messages max to prevent memory leakage
          // Using slice instead of shift() for better GC performance under high tick volume
          const newQ = prev.length >= 100 ? [...prev.slice(-49), msg] : [...prev, msg]
          return newQ
        })
      } catch (err) {
        console.error('WS MSG Parse Error:', err)
      }
    }

    socket.onclose = (event) => {
      if (ws.current === socket) {
        ws.current = null
      }
      if (!mountedRef.current) return
      console.log('WS closed (code:', event.code, '). Reconnecting...')
      setIsConnected(false)
      if (shouldReconnectRef.current) {
        scheduleReconnect()
      }
    }

    socket.onerror = (event) => {
      if (!mountedRef.current || ws.current !== socket) return
      console.error('WS error:', event)
      // Trigger onclose path consistently
      try {
        socket.close()
      } catch {
        scheduleReconnect()
      }
    }
  }, [scheduleReconnect, url])

  useEffect(() => {
    mountedRef.current = true
    shouldReconnectRef.current = true
    clearTimeout(connectInitTimeout.current)
    connectInitTimeout.current = setTimeout(() => {
      if (mountedRef.current && shouldReconnectRef.current) {
        connect()
      }
    }, 40)

    return () => {
      mountedRef.current = false
      shouldReconnectRef.current = false
      clearTimeout(connectInitTimeout.current)
      clearTimeout(reconnectTimeout.current)
      if (ws.current) {
        ws.current.onclose = null // Prevent reconnect on intentional close
        ws.current.close()
        ws.current = null
      }
      setIsConnected(false)
    }
  }, [connect])

  const send = useCallback((data) => {
    if (!data || typeof data !== 'object') return false
    if (ws.current?.readyState === WebSocket.OPEN) {
      try {
        ws.current.send(JSON.stringify(data))
        return true
      } catch (err) {
        console.error('WS send failed:', err)
      }
    }
    return false
  }, [])

  const subscribe = useCallback((symbols) => {
    const safeSymbols = Array.isArray(symbols)
      ? symbols.filter((symbol) => typeof symbol === 'string' && symbol.trim().length > 0)
      : []

    safeSymbols.forEach((symbol) => subscriptions.current.add(symbol))
    if (safeSymbols.length > 0 && ws.current?.readyState === WebSocket.OPEN) {
      try {
        ws.current.send(JSON.stringify({ action: 'subscribe', symbols: safeSymbols }))
      } catch (err) {
        console.error('WS subscribe failed:', err)
      }
    }
  }, [])

  const unsubscribe = useCallback((symbols) => {
    const safeSymbols = Array.isArray(symbols)
      ? symbols.filter((symbol) => typeof symbol === 'string' && symbol.trim().length > 0)
      : []

    safeSymbols.forEach((symbol) => subscriptions.current.delete(symbol))
    if (safeSymbols.length > 0 && ws.current?.readyState === WebSocket.OPEN) {
      try {
        ws.current.send(JSON.stringify({ action: 'unsubscribe', symbols: safeSymbols }))
      } catch (err) {
        console.error('WS unsubscribe failed:', err)
      }
    }
  }, [])

  return { messages, isConnected, send, subscribe, unsubscribe }
}
