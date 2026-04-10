/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        'trade-green': '#22c55e',
        'trade-red': '#ef4444',
        'trade-yellow': '#eab308',
        'trade-dark': '#1e1e2e',
        'trade-darker': '#11111b',
        'trade-card': '#2a2a3c',
      },
    },
  },
  plugins: [],
}
