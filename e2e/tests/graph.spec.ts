import { test, expect } from '@playwright/test'
import { shot } from './helpers'

test.describe('Граф знаний', () => {
  test('обзорный граф: канвас отрисован, есть легенда', async ({ page }, info) => {
    await page.goto('/graph')
    // канвас cytoscape отрисован
    const container = page.getByTestId('graph-canvas')
    await expect(container).toBeVisible({ timeout: 30_000 })
    await expect(container.locator('canvas').first()).toBeVisible({ timeout: 30_000 })
    // дождаться, что граф действительно загрузился (узлы есть)
    await page.waitForFunction(
      () => {
        const cy = (window as unknown as { __cy?: { nodes: () => { length: number } } }).__cy
        return !!cy && cy.nodes().length > 0
      },
      { timeout: 30_000 },
    )
    // легенда типов узлов: заголовок + хотя бы один тип онтологии
    // (набор зависит от данных: fixture — Материал/Процесс; реальный граф может
    // начинаться с Измерений/Условий/Публикаций)
    await expect(page.getByText('Типы узлов (фильтр)')).toBeVisible()
    await expect(
      page
        .getByText(/^(Материал|Процесс|Оборудование|Условие|Утверждение|Публикация|Эксперт|Измерение|Параметр|Эксперимент|Лаборатория\/объект)$/)
        .first(),
    ).toBeVisible()
    await shot(page, info, 'graph')
  })

  test('клик по узлу → карточка; «раскрыть соседей» не падает', async ({ page }) => {
    await page.goto('/graph')
    await expect(page.getByTestId('graph-canvas')).toBeVisible({ timeout: 30_000 })
    await page.waitForFunction(
      () => {
        const cy = (window as unknown as { __cy?: { nodes: () => { length: number } } }).__cy
        return !!cy && cy.nodes().length > 0
      },
      { timeout: 30_000 },
    )
    // тапаем первый узел через test-hook (canvas не даёт DOM-элементов узлов)
    await page.evaluate(() => {
      const cy = (window as unknown as { __cy?: { nodes: () => { first: () => { emit: (e: string) => void } } } }).__cy
      cy?.nodes().first().emit('tap')
    })
    // появилась карточка узла с кнопкой раскрытия соседей
    const expandBtn = page.getByRole('button', { name: /соседей|Раскрыть/i })
    await expect(expandBtn.first()).toBeVisible({ timeout: 15_000 })
    await expandBtn.first().click()
    // после раскрытия граф всё ещё жив (канвас на месте)
    await expect(page.getByTestId('graph-canvas').locator('canvas').first()).toBeVisible()
  })
})
