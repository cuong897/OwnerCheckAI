import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Vite dev server (port 5173) proxy → nginx container (port 80) → backend
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/auth": "http://localhost",
      "/users": "http://localhost",
      "/cameras": "http://localhost",
      "/vehicles": "http://localhost",
      "/watchlists": "http://localhost",
      "/recognition": "http://localhost",
      "/stats": "http://localhost",
      "/events": { target: "http://localhost", changeOrigin: true },
      "/streams": { target: "http://localhost", changeOrigin: true },
      "/health": "http://localhost",
    },
  },
});
