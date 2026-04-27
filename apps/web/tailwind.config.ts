import type { Config } from "tailwindcss";

const config: Config = {
  // Only `.tsx` carries Tailwind class strings; bare-`.ts` files in
  // packages/ui are index barrels and shared TypeScript types. The
  // previous `**/*.{ts,tsx}` glob on `packages/ui` triggered Tailwind's
  // own perf warning ("looks like it's accidentally matching all of
  // node_modules") because the JIT scanner walked type-only files with
  // no class strings on every rebuild. Local app dirs likewise only
  // have classes in `.tsx` files.
  content: [
    "./app/**/*.tsx",
    "./components/**/*.tsx",
    "../../packages/ui/**/*.tsx",
  ],
  theme: {
    extend: {
      colors: {
        border: "hsl(214.3 31.8% 91.4%)",
        input: "hsl(214.3 31.8% 91.4%)",
        ring: "hsl(221.2 83.2% 53.3%)",
        background: "hsl(0 0% 100%)",
        foreground: "hsl(222.2 47.4% 11.2%)",
        primary: {
          DEFAULT: "hsl(221.2 83.2% 53.3%)",
          foreground: "hsl(210 40% 98%)",
        },
        secondary: {
          DEFAULT: "hsl(210 40% 96.1%)",
          foreground: "hsl(222.2 47.4% 11.2%)",
        },
        muted: {
          DEFAULT: "hsl(210 40% 96.1%)",
          foreground: "hsl(215.4 16.3% 46.9%)",
        },
        destructive: {
          DEFAULT: "hsl(0 84.2% 60.2%)",
          foreground: "hsl(210 40% 98%)",
        },
      },
      borderRadius: {
        lg: "0.5rem",
        md: "calc(0.5rem - 2px)",
        sm: "calc(0.5rem - 4px)",
      },
    },
  },
  plugins: [],
};

export default config;
