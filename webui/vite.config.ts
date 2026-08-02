import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// 开发服务器把 /api 代理到后端。
// 默认指向本机后端；要连别的实例就设 VITE_API_TARGET，例如：
//   VITE_API_TARGET=http://192.168.1.10:38473 npm run dev
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.VITE_API_TARGET || 'http://127.0.0.1:38473'

  return {
    plugins: [react(), tailwindcss()],
    base: '/',
    resolve: { alias: { '@': path.resolve(__dirname, './src') } },
    build: {
      // 构建产物直接输出到后端的静态目录，由后端同源托管
      outDir: path.resolve(__dirname, '../api/static'),
      emptyOutDir: false,
    },
    server: {
      host: true,
      proxy: {
        '/api': {
          target,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  }
})
