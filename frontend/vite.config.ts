import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  // Allows deployments behind a reverse-proxy subpath (e.g. https://host/hirato/)
  // by setting VITE_BASE_PATH at build time. Defaults to root for local/standalone use.
  base: process.env.VITE_BASE_PATH || '/',
  plugins: [vue()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:7950',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
