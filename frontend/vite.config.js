import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

const authApiRedirectPlugin = {
  name: 'auth-api-redirect',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      if (req.method !== 'GET') {
        next()
        return
      }

      const path = String(req.url || '').split('?')[0]
      if (path === '/api/v1/auth/login' || path === '/api/v1/auth/signup') {
        const destination = path.endsWith('/signup') ? '/signup' : '/login'
        res.statusCode = 307
        res.setHeader('Location', destination)
        res.end()
        return
      }

      next()
    })
  },
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'https://api.stockai-pro.in'

  return {
    plugins: [react(), authApiRedirectPlugin],
    server: {
      port: 5173,
      host: true,
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          ws: false,
          configure: (proxy) => {
            proxy.on('error', (err, req) => {
              console.error(`[vite-proxy] ${req.method} ${req.url} →`, err.message)
            })
          },
        },
        '/ws': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
        '/live': {
          target: proxyTarget,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
