import { test, expect } from '@playwright/test'
import { shot } from './helpers'

test.describe('Сравнительный анализ', () => {
  test('выбор двух технологий → таблица сравнения', async ({ page }, info) => {
    await page.goto('/compare')
    await expect(page.getByRole('heading', { name: 'Сравнительный анализ' })).toBeVisible()

    // селекты технологий (scoped к карточкам, чтобы не задеть селекты в сайдбаре)
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
  })

  test('автокомплит ищет по всему графу; сравнение процессов с параметрами → таблица не пустая', async ({
    page,
  }, info) => {
    test.skip(info.project.name !== 'mock', 'детерминированный набор технологий — на моках')
    await page.goto('/compare')

    const cardA = page.locator('.card', { hasText: 'Технология A' })
    const cardB = page.locator('.card', { hasText: 'Технология B' })

    // поиск в автокомплите A: «осмос» → серверный /api/concepts (debounce 250 мс)
    await cardA.locator('input').fill('осмос')
    await expect(cardA.getByText(/найдено: \d+ \(по всему графу\)/)).toBeVisible({ timeout: 15_000 })
    // бейдж «есть параметры» для comparable-узлов
    await expect(cardA.getByText('● есть параметры')).toBeVisible()
    await cardA.locator('select').selectOption('proc:reverse_osmosis')

    // поиск в автокомплите B: «нанофильтрация»
    await cardB.locator('input').fill('нанофильтр')
    await expect(cardB.getByText(/найдено: \d+/)).toBeVisible({ timeout: 15_000 })
    await cardB.locator('select').selectOption('proc:nanofiltration')

    await page.getByRole('button', { name: 'Сравнить' }).click()

    // таблица не пустая: есть строки и заполненные значения (не только «— нет данных»)
    const table = page.locator('table')
    await expect(table).toBeVisible({ timeout: 30_000 })
    await expect(table.locator('tbody tr').first()).toBeVisible()
    const cellsText = await table.locator('tbody td').allTextContents()
    const filled = cellsText.filter((t) => t.trim() && !t.includes('— нет данных'))
    expect(filled.length).toBeGreaterThan(3)

    await shot(page, info, 'compare')
  })
})
