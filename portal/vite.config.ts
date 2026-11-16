import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Production assets live under /static/portal/ — Django + whitenoise serve
// STATIC_ROOT at /static/, and the dashboard SPA already owns /static/assets.
// Dev mode keeps base '/' and proxies the API.
//
// PORTAL_API_TARGET points the dev proxy at a deployed environment, e.g.
//   PORTAL_API_TARGET=https://portal.ams-dev.getshaking.live npm run dev
// (changeOrigin sends that hostname, which the backend's host split needs).
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/portal/' : '/',
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: process.env.PORTAL_API_TARGET ?? 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
}))
