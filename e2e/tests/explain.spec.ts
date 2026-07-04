import { test, expect } from '@playwright/test'
import { runGoldenSearch, shot } from './helpers'

test.describe('Объяснимость «Как получен ответ» и верифицируемость', () => {
  test('панель объяснимости: интент, ветки поиска, путь по графу', async ({ page }, info) => {
    await runGoldenSearch(page, 1) // «Циркуляция католита» — есть числа и подграф

    // блок присутствует под ответом
    const panel = page.getByTestId('explain-panel')
    await expect(panel).toBeVisible()
    await expect(panel.getByText('Как получен ответ')).toBeVisible()

    // развернуть
    await panel.getByText('Как получен ответ').click()

    // (а) разобранный интент понятными словами
    await expect(panel.getByText('Как понят запрос')).toBeVisible()
    await expect(panel.getByText(/Материалы:/)).toBeVisible()
    await expect(panel.getByText(/Процессы:/)).toBeVisible()

    // (б) ветки поиска: лексическая / семантическая / графовая
    await expect(panel.getByText('Лексическая')).toBeVisible()
    await expect(panel.getByText('Семантическая')).toBeVisible()
    await expect(panel.getByText('Графовая')).toBeVisible()

    // (в) мини-путь по графу: запрос → концепты → документы
    await expect(panel.getByText('3 · Путь по графу знаний')).toBeVisible()
    await expect(panel.getByText('Открыть весь подграф ответа в графе')).toBeVisible()

    await shot(page, info, 'search-explain')
  })

  test('верифицируемость: числа подсвечены, «Проверить в источнике» открывает документ', async ({
    page,
  }, info) => {
    await runGoldenSearch(page, 1)

    // открыть первую карточку источника
    const citeCards = page.locator('section:has(h3:text("Источники")) button.card')
    await expect(citeCards.first()).toBeVisible()
    await citeCards.first().click()
    await expect(page.getByText('Дословный фрагмент-основание')).toBeVisible()

    // в дословном фрагменте подсвечены числа (.num-hl).
    // На моках цитата гарантированно содержит число+единицу; на live — зависит
    // от реальных данных, поэтому проверяем строго только в mock-проекте.
    if (info.project.name === 'mock') {
      await expect(page.locator('mark.num-hl').first()).toBeVisible()
    }

    // кнопка «Проверить в источнике» открывает карточку документа
    await page.getByRole('button', { name: /Проверить в источнике/ }).click()
    // модал документа открыт (заголовок с кнопкой «Открыть в графе» рендерится сразу)
    await expect(page.getByRole('button', { name: /Открыть в графе/ })).toBeVisible({ timeout: 15_000 })
  })
})
