import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: true,
  },
  build: {
    // D12: код-сплит — cytoscape, markdown и react в отдельные чанки.
    rollupOptions: {
      output: {
        manualChunks: {
          cytoscape: ['cytoscape'],
          markdown: ['react-markdown', 'remark-gfm'],
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
    chunkSizeWarningLimit: 700,
  },
})
