import type { FullConfig } from '@playwright/test'

// Проверка готовности бэкенда для live-проекта. Бэкенд считается уже запущенным
// (uvicorn на :8000). Если live-тесты требуются (E2E_REQUIRE_BACKEND=1, ставит
// npm-скрипт e2e:live), а бэкенд недоступен — падаем с понятной ошибкой.
async function globalSetup(_config: FullConfig) {
  const backend = process.env.VITE_API_URL ?? 'http://localhost:8000'
  const required = process.env.E2E_REQUIRE_BACKEND === '1'

  let ok = false
  let detail = ''
  try {
    const res = await fetch(`${backend}/api/health`, {
      signal: AbortSignal.timeout(5000),
    })
    ok = res.ok
    if (ok) {
      const h = (await res.json()) as Record<string, unknown>
      detail = `status=${h.status} neo4j=${h.neo4j} es=${h.es} corpus_docs=${h.corpus_docs}`
    } else {
      detail = `HTTP ${res.status}`
    }
  } catch (e) {
    detail = e instanceof Error ? e.message : String(e)
  }

  if (ok) {
    console.log(`[e2e] backend OK @ ${backend} — ${detail}`)
    return
  }

  const msg =
    `\n[e2e] Бэкенд НЕ доступен на ${backend} (${detail}).\n` +
    `      Live-тестам нужен запущенный API. Подними его:\n` +
    `        cd backend && NO_PROXY=localhost ../.venv-c/bin/python -m uvicorn app.main:app --port 8000\n` +
    `      И проверь docker (neo4j + es): docker compose ps\n`

  if (required) {
    throw new Error(msg)
  }
  console.warn(msg + '      (live-проект не запрошен — продолжаю только для mock)')
}

export default globalSetup
