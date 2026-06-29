import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: resolve(__dirname, '../static/dist'),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8080',
      '/events': {
        target: 'http://localhost:8080',
        ws: false,
        changeOrigin: true,
      },
    },
  },
})
