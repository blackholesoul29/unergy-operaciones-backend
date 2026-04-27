/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  theme: {
    extend: {
      colors: {
        unergy: {
          purple:  '#915BD8', // Púrpura Energético
          deep:    '#2C2039', // Púrpura Profundo
          avena:   '#FDFAF7', // Avena
          yellow:  '#F6FF72', // Amarillo Solar
          'purple-light': '#B08AE2',
          'purple-dark':  '#6E3FB8',
          'deep-light':   '#3D2F52',
        },
      },
      fontFamily: {
        display: ['"Forma DJR Display"', 'Inter', 'sans-serif'],
        body:    ['Lato', 'Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
