import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server proxies API + media to the FastAPI backend on :8765.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://127.0.0.1:8765',
      '/media': 'http://127.0.0.1:8765',
    },
  },
})
