/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Научно-индустриальная тёмная палитра
        ink: {
          900: '#0b0f14',
          850: '#0f151c',
          800: '#131b24',
          700: '#1b2530',
          600: '#26333f',
          500: '#37485a',
        },
        accent: {
          DEFAULT: '#3ea6ff',
          soft: '#7cc4ff',
          dim: '#1e4d73',
        },
        node: {
          material: '#4fc3f7',
          process: '#81c784',
          equipment: '#ffb74d',
          condition: '#ba68c8',
          assertion: '#f06292',
          publication: '#90a4ae',
          expert: '#fff176',
          facility: '#4db6ac',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
    },
  },
  plugins: [],
}
