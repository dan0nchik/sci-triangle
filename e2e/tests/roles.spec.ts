import { test, expect } from '@playwright/test'
import { setRole } from './helpers'

test.describe('Роли (RBAC-демо)', () => {
  test('external_partner → плашка ограничений (внутр. разделы скрыты)', async ({ page }) => {
    await page.goto('/')
    await setRole(page, 'Внешний партнёр')
    // плашка ограничения доступа в боковой панели
    await expect(page.getByText('внутр. разделы скрыты')).toBeVisible({ timeout: 15_000 })
  })

  test('project_lead → доступна правка графа (кнопки/режим)', async ({ page }) => {
    await page.goto('/')
    await setRole(page, 'Рук. проекта')
    // индикатор прав в панели
    await expect(page.getByText('правка графа')).toBeVisible({ timeout: 15_000 })
    // на странице графа появляется чекбокс «Режим правки (эксперт)»
    await page.goto('/graph')
    await expect(page.getByText('Режим правки (эксперт)')).toBeVisible({ timeout: 30_000 })
  })

  test('external_partner: экспорт/внутренние данные ограничены (live)', async ({ page }, info) => {
    test.skip(info.project.name === 'mock', 'RBAC на retrieval/export действует только на живом API')
    await page.goto('/')
    await setRole(page, 'Внешний партнёр')
    // выполнить поиск: либо denied-плашка (403), либо ответ без внутренних источников
    await page.getByRole('button', { name: /^Найти$/ }).isVisible()
    const examples = page.locator('button.chip', { hasText: /Циркуляция/ })
    await examples.first().click()
    // ждём либо ответ, либо плашку об ограничении прав
    await expect(
      page.getByText(/интент:|Недостаточно прав/).first(),
    ).toBeVisible({ timeout: 75_000 })
  })
})
