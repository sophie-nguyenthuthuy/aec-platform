import type { Config } from "tailwindcss";

/**
 * Shared Tailwind preset. Apps extend this with their own `content` globs and
 * any app-specific theme overrides.
 */
const preset: Partial<Config> = {
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        brand: {
          50: "#eef7ff",
          100: "#d9ecff",
          500: "#2563eb",
          600: "#1d4ed8",
          700: "#1e40af",
        },
        surface: {
          DEFAULT: "hsl(var(--surface) / <alpha-value>)",
          muted: "hsl(var(--surface-muted) / <alpha-value>)",
        },
        border: "hsl(var(--border) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui"],
        mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular"],
      },
      borderRadius: {
        lg: "0.625rem",
        xl: "0.875rem",
      },
    },
  },
};

export default preset;
