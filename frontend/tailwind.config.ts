import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#F8FAFC",
        surface: "#FFFFFF",
        border: "#E2E8F0",
        "surface-hover": "#F1F5F9",
        text: "#0F172A",
        muted: "#475569",
        accent: "#4F46E5",
        approve: "#16A34A",
        danger: "#DC2626",
        warn: "#D97706",
      },
      borderRadius: {
        DEFAULT: "8px",
      },
      fontFamily: {
        sans: ["Fira Sans", "system-ui", "sans-serif"],
        mono: ["Fira Code", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
