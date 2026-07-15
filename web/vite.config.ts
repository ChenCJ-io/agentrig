import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 前端 dev server 代理 /api 与 /mcp 到后端（agentrig serve，默认 8000）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/mcp": "http://127.0.0.1:8000",
    },
  },
});
