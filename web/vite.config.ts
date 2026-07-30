import { reactRouter } from "@react-router/dev/vite";
import { defineConfig } from "vite";

// 前端 dev server 代理 /api 与 /mcp 到后端（agentrig serve，默认 8000）
export default defineConfig({
  base: "/",
  plugins: [reactRouter()],
  resolve: {
    tsconfigPaths: true,
  },
  preview: {
    host: "127.0.0.1",
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/mcp": "http://127.0.0.1:8000",
    },
  },
});
