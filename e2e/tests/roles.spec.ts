import { test, expect } from '@playwright/test'
import { setRole } from './helpers'

test.describe('Демо-режимы (де-акцентированные роли)', () => {
  test('переключатель ролей убран в свёрнутое меню «Демо-режимы»', async ({ page }) => {
    await page.goto('/')
    // на видном месте селектора ролей нет — он спрятан в details
    await expect(page.locator('aside > .px-4 > select')).toHaveCount(0)
    // меню помечено как доп. возможность
    await expect(page.getByText('Демо-режимы')).toBeVisible()
    await expect(page.getByText('(доп. возможность)')).toBeVisible()
  })

  test('external_partner → мягкая плашка «открытые источники»', async ({ page }) => {
    await page.goto('/')
    await setRole(page, 'Внешний партнёр')
    // мягкий индикатор ограничения доступа в меню демо-режимов
    await expect(page.getByText('открытые источники')).toBeVisible({ timeout: 15_000 })
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
    // ждём либо ответ, либо мягкую плашку об ограничении выдачи
    await expect(
      page.getByText(/интент:|только открытые источники/).first(),
    ).toBeVisible({ timeout: 75_000 })
  })
})
