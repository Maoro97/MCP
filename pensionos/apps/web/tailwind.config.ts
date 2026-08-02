import type { Config } from 'tailwindcss';

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: { sans: ['Assistant', 'Rubik', 'system-ui', 'sans-serif'] },
      colors: {
        ink: { DEFAULT: '#101828', muted: '#475467', faint: '#98a2b3' },
        surface: { DEFAULT: '#ffffff', sunken: '#f7f8fa', line: '#e4e7ec' },
        brand: { DEFAULT: '#1f5f8b', soft: '#eaf2f8' },
        risk: { high: '#b42318', med: '#b54708', low: '#175cd3', ok: '#067647' },
      },
    },
  },
  plugins: [],
} satisfies Config;
