import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the React app runs on :5173 and proxies API/admin calls to Django on :8000.
const backend = process.env.VITE_BACKEND_URL || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, changeOrigin: true },
      "/admin/": { target: backend, changeOrigin: true },
      "/static/": { target: backend, changeOrigin: true },
    },
  },
});
