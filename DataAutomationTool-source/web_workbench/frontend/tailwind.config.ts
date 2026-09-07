import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(214 32% 88%)",
        background: "hsl(215 35% 96%)",
        foreground: "hsl(222 47% 11%)",
        muted: "hsl(215 20% 48%)",
        card: "hsl(0 0% 100%)",
        primary: "hsl(221 83% 53%)",
        sidebar: "hsl(222 47% 11%)",
      },
      boxShadow: {
        soft: "0 16px 40px rgba(15, 23, 42, 0.08)",
      },
    },
  },
  plugins: [],
} satisfies Config;
