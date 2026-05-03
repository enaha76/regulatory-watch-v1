import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import { defineConfig } from 'vite';

// The admin SPA is served by Express at /admin, so it must be built with
// base="/admin/" and emitted into dist/admin/. In dev, /api/* requests are
// proxied to the Express server on :3001 so the React app talks to the same
// origin it will in production.
export default defineConfig(() => ({
  plugins: [react(), tailwindcss()],
  base: '/admin/',
  build: {
    outDir: 'dist/admin',
    emptyOutDir: true,
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, '.'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:3001',
    },
    hmr: process.env.DISABLE_HMR !== 'true',
  },
}));
