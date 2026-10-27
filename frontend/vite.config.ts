import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Development only: the API itself remains bound to localhost.
export default defineConfig({ plugins: [react()], server: { proxy: { '/api': 'http://127.0.0.1:8000' } } })
