import fs from 'fs'
import path from 'path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

function getVersion(): string {
  const pyproject = fs.readFileSync(path.resolve(__dirname, '../pyproject.toml'), 'utf-8')
  const match = pyproject.match(/^version\s*=\s*"(.+)"/m)
  return match ? match[1] : '0.0.0'
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    __APP_VERSION__: JSON.stringify(getVersion()),
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:3982',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom'],
          router: ['react-router-dom'],
          query: ['@tanstack/react-query'],
        },
      },
    },
    target: 'es2020',
    sourcemap: false,
    chunkSizeWarningLimit: 500,
  },
})
