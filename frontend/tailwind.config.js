/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // LUNA deep-medical palette
        abyss: "#05080F",          // near-black background
        midnight: "#0A1020",       // primary surface
        deepnavy: "#0F1A2E",       // elevated surface
        slate: "#1A2540",          // card background
        steel: "#2A3553",          // borders / dividers
        mist: "#6B7A99",           // muted text
        frost: "#A8B4CE",          // secondary text
        ice: "#E6ECF5",            // primary text
        cyan: {
          DEFAULT: "#00E5FF",      // accent
          dim: "#00A8BF",
          glow: "#66F0FF",
        },
        signal: {
          red: "#FF4D6D",          // high risk
          amber: "#FFB547",        // medium risk
          green: "#4ADE80",        // low risk / OK
        },
      },
      fontFamily: {
        display: ['"JetBrains Mono"', "monospace"],
        sans: ['"Outfit"', "system-ui", "sans-serif"],
      },
      boxShadow: {
        "glow-cyan": "0 0 24px rgba(0, 229, 255, 0.25)",
        "glow-cyan-lg": "0 0 40px rgba(0, 229, 255, 0.35)",
        "inset-border": "inset 0 0 0 1px rgba(168, 180, 206, 0.08)",
      },
      backgroundImage: {
        "grid-faint":
          "linear-gradient(rgba(168,180,206,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(168,180,206,0.04) 1px, transparent 1px)",
        "radial-glow":
          "radial-gradient(circle at 50% 0%, rgba(0, 229, 255, 0.12), transparent 60%)",
      },
      animation: {
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-up": "fadeUp 0.6s ease-out forwards",
      },
      keyframes: {
        fadeUp: {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};
