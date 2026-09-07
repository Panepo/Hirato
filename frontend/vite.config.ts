import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// Shared with the backend's ROOT_PATH (ASGI root_path) for reverse-proxy subpath deployments.
const rootPath = (process.env.ROOT_PATH || '').replace(/\/+$/, '')

// https://vite.dev/config/
export default defineConfig({
  base: rootPath ? `${rootPath}/` : '/',
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
