import { test, expect } from '@playwright/test'
import { shot } from './helpers'

test.describe('Сравнительный анализ', () => {
  test('выбор двух технологий → таблица сравнения', async ({ page }, info) => {
    await page.goto('/compare')
    await expect(page.getByRole('heading', { name: 'Сравнительный анализ' })).toBeVisible()

    // селекты технологий (scoped к карточкам, чтобы не задеть role-select в сайдбаре)
    const selectA = page.locator('.card', { hasText: 'Технология A' }).locator('select')
    const selectB = page.locator('.card', { hasText: 'Технология B' }).locator('select')
    await expect(selectA).toBeVisible({ timeout: 30_000 })

    // дождаться, что список технологий подгрузился (overview). На реальном графе
    // Process/Material-узлов может быть мало (экстракция ещё идёт) — достаточно 1.
    await expect
      .poll(async () => selectA.locator('option').count(), { timeout: 30_000 })
      .toBeGreaterThanOrEqual(1)

    // выбрать две технологии (разные, если данных хватает)
    const values = await selectA.locator('option').evaluateAll((os) =>
      (os as HTMLOptionElement[]).map((o) => o.value),
    )
    await selectA.selectOption(values[0])
    await selectB.selectOption(values[1] ?? values[0])

    await page.getByRole('button', { name: 'Сравнить' }).click()

    // таблица сравнения
    const table = page.locator('table')
    await expect(table).toBeVisible({ timeout: 30_000 })
    await expect(table.locator('tbody tr').first()).toBeVisible()
    await shot(page, info, 'compare')
  })
})
