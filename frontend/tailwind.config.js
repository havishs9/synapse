/** Colors map to CSS variables in src/styles/tokens.css (light + dark). */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    fontFamily: {
      sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
      mono: ['"IBM Plex Mono"', "ui-monospace", "monospace"],
    },
    fontSize: { xs: ["12px", "1.5"], sm: ["13px", "1.5"], base: ["14px", "1.5"], md: ["16px", "1.45"], lg: ["20px", "1.3"], xl: ["24px", "1.3"] },
    extend: {
      colors: {
        bg: "var(--bg)", surface: "var(--surface)", "surface-2": "var(--surface-2)", border: "var(--border)",
        ink: "var(--ink)", "ink-2": "var(--ink-2)", "ink-3": "var(--ink-3)", danger: "var(--danger)", ok: "var(--ok)",
        focus: "var(--focus)",
      },
      borderRadius: { DEFAULT: "8px" },
    },
  },
};
