/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        trading: {
          bg: '#0b0f14',
          surface: 'rgba(255,255,255,0.03)',
          accent: '#14b8a6',
          buy: '#10b981',
          sell: '#ef4444',
          muted: '#64748b',
        },
        'terminal': {
          bg: '#0b0f14',
          surface: '#111827',
          border: '#334155',
          accent: '#14b8a6',
          buy: '#10b981',
          sell: '#ef4444',
          muted: '#64748b',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'IBM Plex Mono', 'monospace'],
      },
      backgroundImage: {
        'grid-pattern': 'linear-gradient(rgba(20,184,166,0.03) 1px, transparent 1px), linear-gradient(90deg, rgba(20,184,166,0.03) 1px, transparent 1px)',
      },
      animation: {
        'pulse-soft': 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'glow': 'glow 2s ease-in-out infinite alternate',
      },
      keyframes: {
        glow: {
          '0%': { boxShadow: '0 0 12px rgba(20,184,166,0.2)' },
          '100%': { boxShadow: '0 0 24px rgba(20,184,166,0.4)' },
        },
      },
    },
  },
  plugins: [],
}
