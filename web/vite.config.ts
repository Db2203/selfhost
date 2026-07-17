import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, /api is proxied to the compose stack's Caddy (self-signed TLS).
// When running the API natively (no Docker), point it at uvicorn instead:
//   API_PROXY=http://localhost:8000 npm run dev
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: process.env.API_PROXY ?? "https://localhost",
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
