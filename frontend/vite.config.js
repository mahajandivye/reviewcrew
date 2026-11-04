import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// The dev server proxies API calls to FastAPI, so the browser only ever talks
// to http://localhost:5174. That keeps cookies/CORS out of the picture during
// development (the backend also enables CORS for direct access).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
