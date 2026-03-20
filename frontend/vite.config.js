import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // REST API — force IPv4 (127.0.0.1) to avoid ECONNREFUSED on Windows/Node18+
      // where `localhost` resolves to ::1 (IPv6) but uvicorn binds 0.0.0.0 (IPv4 only).
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: false, // WebSocket connects directly (see useWebsocket.js / App.jsx)
        configure: (proxy) => {
          proxy.on('error', (err, req) => {
            console.error(`[vite-proxy] ${req.method} ${req.url} →`, err.message)
          })
        },
      },
    },
  },
})
