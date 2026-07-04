/** @type {import('tailwindcss').Config} */
// Фирменная палитра ПАО ГМК «Норильский никель» (Стандарт «Фирменный стиль», v1.1).
// Источник цветов — стр. 35 брендбука (фирменная цветовая палитра),
// типографика — стр. 36 (Proxima Nova → свободный аналог Mulish/Montserrat + Tahoma-fallback).
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Фирменные константы (для логотипа, футера, точечных акцентов)
        brand: {
          blue: '#0077C8',   // синий · Pantone 3005 · RGB 0.119.200 (стр. 35)
          dark: '#004C97',   // тёмно-синий · Pantone 2945 · RGB 0.76.151 (стр. 35)
          gray: '#626262',   // серый · Cool Gray 10 · RGB 98.98.98 (стр. 35)
          'gray-light': '#C8C8C8', // светло-серый · Cool Gray 3 (стр. 35)
        },
        // Основной акцент = фирменный синий
        accent: {
          DEFAULT: '#0077C8',
          soft: '#005A99',   // затемнённый синий: ссылки/hover на светлом фоне
          dim: '#8FC3EA',    // светлый синий: тонкие заливки/бордеры активных состояний
        },
        // Поверхности (светлая тема как на nornickel.ru): имена ink-* сохранены для обратной совместимости
        ink: {
          900: '#EEF2F7', // фон приложения / холст графа
          850: '#F7F9FB', // сайдбар, дровер, шапки модалок, вложенные панели
          800: '#FFFFFF', // карточки, инпуты
          700: '#E3E9F0', // чипы, бордеры карточек, hover
          600: '#CAD5E0', // бордеры инпутов
          500: '#93A1B0',
        },
        // Текст (foreground)
        fg: {
          DEFAULT: '#16222E', // заголовки
          body: '#33414E',    // основной текст
          muted: '#5E6B78',   // вторичный
          faint: '#95A1AD',   // третичный / placeholder
        },
        // Палитра типов узлов графа — гармоничная производная от бренда, различимая на светлом холсте
        node: {
          material: '#0077C8',   // фирменный синий
          process: '#17A2A2',    // бирюзовый
          equipment: '#E07B00',  // оранжевый
          condition: '#7A5AC2',  // фиолетовый
          assertion: '#D6336C',  // пурпурный (утверждения)
          publication: '#64748B',// серо-синий
          expert: '#C79200',     // золотой
          facility: '#2E8B72',   // изумрудный
          parameter: '#6D5BB0',  // сине-фиолетовый
          measurement: '#0E9AA7',// сине-циан
          experiment: '#A5744B', // коричневый
        },
      },
      fontFamily: {
        // Свободный аналог Proxima Nova + фирменный системный fallback Tahoma (стр. 36)
        sans: ['Mulish', 'Tahoma', 'system-ui', 'Segoe UI', 'Roboto', 'sans-serif'],
        display: ['Montserrat', 'Mulish', 'Tahoma', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        // Скругление в духе носителей бренда (плашка/скругление углов, стр. 31–34)
        xl: '0.875rem',
        '2xl': '1.25rem',
      },
      boxShadow: {
        card: '0 1px 2px rgba(16,34,46,0.04), 0 8px 24px -12px rgba(16,34,46,0.10)',
        panel: '0 12px 40px -12px rgba(16,34,46,0.22)',
      },
    },
  },
  plugins: [],
}
