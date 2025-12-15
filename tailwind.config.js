/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pos/templates/**/*.html',
    './pos/**/*.py',
  ],
  theme: {
    extend: {
      colors: {
        brand: {
          100: '#f9f9f5', // Background
          200: '#e7ecda', // Accent 2
          300: '#cddecc', // Accent 1
          400: '#3f897a', // Secondary
          500: '#5592a3', // Primary
        }
      }
    },
  },
  plugins: [],
}
