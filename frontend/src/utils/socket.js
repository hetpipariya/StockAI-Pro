const managers = new Map()

class SocketManager {
  constructor(url) {
    this.url = url
    this.ws = null
    this.authToken = null
    this.refCount = 0
    this.shouldReconnect = false
    this.reconnectTimer = null
    this.connectTimer = null
    this.backoffMs = 1000
    this.maxBackoffMs = 10000
    this.reconnectableCloseCodes = new Set([1001, 1005, 1006, 1011, 1012, 1013])
    this.subscriptions = new Set()
    this.messageListeners = new Set()
    this.connectionListeners = new Set()
    this.pendingTick = null
    this.tickFlushTimer = null
  }

  notifyConnection(isConnected) {
    this.connectionListeners.forEach((listener) => {
      try {
        listener(isConnected)
      } catch {
      }
    })
  }

  notifyMessage(message) {
    this.messageListeners.forEach((listener) => {
      try {
        listener(message)
      } catch {
      }
    })
  }

  flushTick() {
    this.tickFlushTimer = null
    if (!this.pendingTick) return
    this.notifyMessage(this.pendingTick)
    this.pendingTick = null
  }

  scheduleReconnect() {
    if (!this.shouldReconnect) return
    clearTimeout(this.reconnectTimer)
    const delay = this.backoffMs
    this.reconnectTimer = setTimeout(() => {
      if (!this.shouldReconnect) return
      this.backoffMs = Math.min(Math.round(this.backoffMs * 1.5), this.maxBackoffMs)
      this.connect()
    }, delay)
  }

  connect() {
    if (!this.url) return
    if (this.ws?.readyState === WebSocket.OPEN || this.ws?.readyState === WebSocket.CONNECTING) return

    let socket = null
    try {
      socket = new WebSocket(this.url)
      this.ws = socket
    } catch {
      this.scheduleReconnect()
      return
    }

    socket.onopen = () => {
      if (this.ws !== socket) return
      this.backoffMs = 1000
      this.notifyConnection(true)
      this.sendAuth()
      if (this.subscriptions.size > 0) {
        this.send({ action: 'subscribe', symbols: Array.from(this.subscriptions) })
      }
    }

    socket.onmessage = (event) => {
      if (this.ws !== socket) return
      try {
        const msg = JSON.parse(event.data)
        if (!msg || typeof msg !== 'object') return

        if (msg.type === 'heartbeat') {
          this.send({ action: 'pong' })
          return
        }

        if (msg.type === 'tick') {
          this.pendingTick = msg
          if (!this.tickFlushTimer) {
            this.tickFlushTimer = setTimeout(() => this.flushTick(), 32)
          }
          return
        }

        this.notifyMessage(msg)
      } catch {
      }
    }

    socket.onclose = (event) => {
      if (this.ws === socket) {
        this.ws = null
      }
      this.notifyConnection(false)
      if (this.shouldReconnect && this.reconnectableCloseCodes.has(event.code)) {
        this.scheduleReconnect()
      }
    }

    socket.onerror = () => {
      if (this.ws !== socket) return
      try {
        socket.close()
      } catch {
        this.scheduleReconnect()
      }
    }
  }

  attach() {
    this.refCount += 1
    this.shouldReconnect = true
    clearTimeout(this.connectTimer)
    this.connectTimer = setTimeout(() => this.connect(), 40)
  }

  detach() {
    this.refCount = Math.max(0, this.refCount - 1)
    if (this.refCount > 0) return

    this.shouldReconnect = false
    clearTimeout(this.connectTimer)
    clearTimeout(this.reconnectTimer)
    clearTimeout(this.tickFlushTimer)
    this.tickFlushTimer = null
    this.pendingTick = null

    if (this.ws) {
      const socket = this.ws
      this.ws = null
      socket.onclose = null
      try {
        socket.close()
      } catch {
      }
    }

    this.notifyConnection(false)
  }

  onMessage(listener) {
    this.messageListeners.add(listener)
    return () => this.messageListeners.delete(listener)
  }

  onConnection(listener) {
    this.connectionListeners.add(listener)
    return () => this.connectionListeners.delete(listener)
  }

  send(payload) {
    if (!payload || typeof payload !== 'object') return false
    if (this.ws?.readyState !== WebSocket.OPEN) return false
    try {
      this.ws.send(JSON.stringify(payload))
      return true
    } catch {
      return false
    }
  }

  setAuthToken(token) {
    this.authToken = typeof token === 'string' && token.trim() ? token.trim() : null
    this.sendAuth()
  }

  sendAuth() {
    if (!this.authToken) return false
    return this.send({ action: 'auth', token: this.authToken })
  }

  subscribe(symbols) {
    const safe = Array.isArray(symbols)
      ? symbols
          .filter((symbol) => typeof symbol === 'string' && symbol.trim())
          .map((symbol) => symbol.trim())
      : []
    safe.forEach((symbol) => this.subscriptions.add(symbol))
    if (safe.length > 0) {
      this.send({ action: 'subscribe', symbols: safe })
    }
  }

  unsubscribe(symbols) {
    const safe = Array.isArray(symbols)
      ? symbols
          .filter((symbol) => typeof symbol === 'string' && symbol.trim())
          .map((symbol) => symbol.trim())
      : []
    safe.forEach((symbol) => this.subscriptions.delete(symbol))
    if (safe.length > 0) {
      this.send({ action: 'unsubscribe', symbols: safe })
    }
  }

  isSubscribed(symbol) {
    return this.subscriptions.has(symbol)
  }
}

export const getSocketManager = (url) => {
  if (!managers.has(url)) {
    managers.set(url, new SocketManager(url))
  }
  return managers.get(url)
}
