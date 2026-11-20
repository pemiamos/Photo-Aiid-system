import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // 本地视觉预分类页面（后端直接托管，见 backend/main.py 的 /fast 路由）
      '/fast': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
