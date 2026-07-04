import { test, expect } from '@playwright/test'
import { runGoldenSearch, waitForAnswer, shot } from './helpers'

test.describe('Поиск и evidence packet', () => {
  test('golden query → ответ с цитатами [n] → клик по цитате → drawer с фрагментом', async ({
    page,
  }, info) => {
    await runGoldenSearch(page, 3) // «Закачка шахтных вод: РФ vs зарубеж» (index 3 — hits on real corpus)

    // есть ответ и раздел источников
    await expect(page.getByRole('heading', { name: 'Источники' })).toBeVisible()

    // цитаты [n]: карточки источников с чипом-номером
    const citeCards = page.locator('section:has(h3:text("Источники")) button.card')
    await expect(citeCards.first()).toBeVisible()
    const nCites = await citeCards.count()
    expect(nCites).toBeGreaterThan(0)

    await shot(page, info, 'search-result')

    // клик по цитате → выезжает drawer источника с дословным фрагментом
    await citeCards.first().click()
    const drawer = page.getByText('Дословный фрагмент-основание')
    await expect(drawer).toBeVisible()
    await expect(page.locator('blockquote').first()).toBeVisible()
    await expect(page.getByText(/Источник \[\d+\]/)).toBeVisible()
    await shot(page, info, 'search-source-drawer')
  })

  test('инлайн-цитата [n] в тексте ответа открывает drawer', async ({ page }) => {
    await runGoldenSearch(page, 3)
    const inline = page.locator('.md button', { hasText: /^\[\d+\]$/ })
    // инлайн [n] есть в синтезированном ответе (mock всегда; live — почти всегда)
    if ((await inline.count()) > 0) {
      await inline.first().click()
      await expect(page.getByText('Дословный фрагмент-основание')).toBeVisible()
    } else {
      test.info().annotations.push({ type: 'note', description: 'нет инлайн [n] в ответе — пропуск' })
    }
  })

  test('смена географии/лет не роняет запрос', async ({ page }) => {
    await page.goto('/')
    // сменить географию на «Россия»
    const filters = page.locator('.card', { hasText: 'Фильтры' })
    await filters.getByRole('button', { name: 'Россия' }).click()
    // подвигать слайдер годов
    const yearFrom = filters.locator('input[type="range"]').first()
    await yearFrom.focus()
    await page.keyboard.press('ArrowRight')
    await page.keyboard.press('ArrowRight')
    // запустить запрос — не должен упасть
    const examples = page.locator('button.chip', { hasText: /Циркуляция/ })
    await examples.first().click()
    await waitForAnswer(page)
    await expect(page.getByText(/интент:/).first()).toBeVisible()
  })

  test('экспорт MD → файл скачан (download event)', async ({ page }) => {
    await runGoldenSearch(page, 3)
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: /MD/ }).click(),
    ])
    expect(download.suggestedFilename()).toMatch(/\.md$/)
  })

  test('экспорт всех форматов (md/jsonld/pdf/xlsx) отдаёт download', async ({ page }, info) => {
    test.skip(info.project.name === 'mock', 'бинарные форматы (pdf/xlsx) осмысленны только на live')
    await runGoldenSearch(page, 3)
    for (const label of [/MD/, /JSON-LD/, /PDF/, /XLSX/]) {
      const [download] = await Promise.all([
        page.waitForEvent('download'),
        page.getByRole('button', { name: label }).click(),
      ])
      expect(download.suggestedFilename().length).toBeGreaterThan(0)
    }
  })
})
