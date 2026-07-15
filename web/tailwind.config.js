/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // 侧栏深色 + 主区浅色 + teal 主色 + 状态色（对标设计稿）
        sidebar: { DEFAULT: "#1a1d23", hover: "#252932", active: "#2d3340" },
        canvas: "#f8f9fa",
        ink: { DEFAULT: "#1f2937", soft: "#374151", mute: "#6b7280", faint: "#9ca3af" },
        accent: {
          DEFAULT: "#10b981",
          hover: "#059669",
          soft: "#ecfdf5",
          border: "#a7f3d0",
        },
        pass: "#10b981",
        fail: "#ef4444",
        review: "#f59e0b",
        draft: "#6b7280",
        line: "#e5e7eb",
        card: "#ffffff",
      },
      fontFamily: {
        sans: [
          "Inter",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "PingFang SC",
          "Microsoft YaHei",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
