import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Same-origin API in dev so `Set-Cookie` from OAuth + `/auth/me` share the page host
    // (avoids SameSite / localhost vs 127.0.0.1 issues with credentialed cross-origin fetch).
    proxy: {
      "/auth": { target: "http://localhost:8000", changeOrigin: true },
      "/chat": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
});
