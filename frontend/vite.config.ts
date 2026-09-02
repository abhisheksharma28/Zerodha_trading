import path from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(import.meta.dirname, './src'),
    },
  },
  build: {
    // Route chunks are small after code-splitting; the charting libs are the
    // only genuinely large payloads and get their own long-cached vendor
    // chunks so a deploy doesn't invalidate them.
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('recharts') || id.includes('d3-') || id.includes('victory-vendor'))
            return 'charts'
          if (id.includes('lightweight-charts')) return 'lwcharts'
          if (
            id.includes('react-dom') ||
            id.includes('react-router') ||
            id.includes('/react/') ||
            id.includes('@tanstack')
          )
            return 'react-vendor'
        },
      },
    },
  },
  server: {
    host: true,
    port: 5173,
  },
})
