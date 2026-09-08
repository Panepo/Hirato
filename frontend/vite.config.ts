import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

// Shared with the backend's ROOT_PATH (ASGI root_path) for reverse-proxy subpath deployments.
export default defineConfig(({ mode }) => {
  // Load env variables based on current mode (production, development, etc.)
  const env = loadEnv(mode, process.cwd(), '')
  const rootPath = (env.VITE_ROOT_PATH || '').replace(/\/+$/, '/hirato')

  return {
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
  }
})

