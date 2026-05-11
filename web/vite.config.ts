import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In production builds, assets are referenced under /static/ to align with
// Django + whitenoise serving STATIC_ROOT at /static/. Dev mode keeps base '/'
// so the Vite dev server proxy works.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/' : '/',
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/admin': 'http://localhost:8000',
      '/health': 'http://localhost:8000',
    },
  },
}))
