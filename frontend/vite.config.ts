/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const hmrClientPort = process.env.VITE_HMR_CLIENT_PORT;
const usePolling = process.env.VITE_USE_POLLING === "1";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: Number(process.env.VITE_DEV_PORT || 5173),
    ...(hmrClientPort
      ? { hmr: { clientPort: Number(hmrClientPort) } }
      : {}),
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
