import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// dev：Vite 独立端口，/api 代理到 FastAPI；build：产物直接进后端静态目录
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  build: {
    outDir: '../backend/app/static/dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          antd: ['antd', '@ant-design/icons'],
          charts: ['echarts'],
          query: ['@tanstack/react-query'],
        },
      },
    },
  },
})
