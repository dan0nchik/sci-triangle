import { defineConfig, devices } from '@playwright/test'

// Корпоративный HTTP(S)_PROXY из окружения ломает localhost (Chromium гонит
// localhost:5173/5174 через прокси → ERR_PROXY_CONNECTION_FAILED). Снимаем прокси
// для всех дочерних процессов (chromium, vite) — тесты ходят только на localhost.
for (const k of ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'ALL_PROXY', 'all_proxy']) {
  delete process.env[k]
}
process.env.NO_PROXY = 'localhost,127.0.0.1'
process.env.no_proxy = 'localhost,127.0.0.1'

// Two projects:
//   mock — фронт БЕЗ VITE_API_URL (встроенные моки), порт 5173
//   live — фронт С  VITE_API_URL=http://localhost:8000, порт 5174 (бэкенд уже поднят)
// Оба vite-сервера поднимает сам Playwright (webServer). Готовность бэкенда для live
// проверяется в globalSetup (см. global-setup.ts) — падает с понятной ошибкой.

const FRONTEND = '../frontend'
const MOCK_PORT = 5173
const LIVE_PORT = 5174
const BACKEND_URL = process.env.VITE_API_URL ?? 'http://localhost:8000'

export default defineConfig({
  testDir: './tests',
  globalSetup: './global-setup.ts',
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'playwright-report' }]],
  use: {
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'mock',
      use: { ...devices['Desktop Chrome'], baseURL: `http://localhost:${MOCK_PORT}` },
    },
    {
      name: 'live',
      use: { ...devices['Desktop Chrome'], baseURL: `http://localhost:${LIVE_PORT}` },
    },
  ],
  webServer: [
    {
      // mock: без VITE_API_URL (пустая строка => isMockMode=true)
      command: `npm --prefix ${FRONTEND} run dev -- --port ${MOCK_PORT} --strictPort`,
      url: `http://localhost:${MOCK_PORT}`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { VITE_API_URL: '' },
    },
    {
      // live: VITE_API_URL -> реальный бэкенд
      command: `npm --prefix ${FRONTEND} run dev -- --port ${LIVE_PORT} --strictPort`,
      url: `http://localhost:${LIVE_PORT}`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { VITE_API_URL: BACKEND_URL },
    },
  ],
})
