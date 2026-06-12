/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  base: process.env.BASE_URL || "/",
  plugins: [react()],
  build: {
    // Bundle all CSS into one file so lazy-loaded routes don't briefly render
    // unstyled while their per-chunk CSS is still being fetched.
    cssCodeSplit: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 28173,
    strictPort: true,
    allowedHosts: true,
    hmr: {
      clientPort: 28173,
      protocol: "ws",
    },
    proxy: {
      "/api/v1/realtime/ws": {
        target: "ws://localhost:28080",
        ws: true,
        rewrite: (p) => p,
      },
      "/api/ws": {
        target: "ws://localhost:28080",
        ws: true,
        rewrite: (p) => p,
      },
      "/api": {
        target: "http://localhost:28080",
        changeOrigin: true,
      },
      "/ws": {
        target: "http://localhost:28080",
        ws: true,
      },
    },
  },
});
