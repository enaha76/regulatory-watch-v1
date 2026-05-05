import { defineConfig } from "vite";
import path from "path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    // Proxy API calls to the FastAPI backend during dev so the React app
    // talks to the same origin it will in production. Override with
    // VITE_API_BASE if the API runs somewhere else (e.g. inside Docker).
    proxy: {
      "/api": {
        target: process.env.VITE_API_BASE || "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
});
