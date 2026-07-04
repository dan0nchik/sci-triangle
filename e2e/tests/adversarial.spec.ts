import { test, expect } from '@playwright/test'
import { waitForAnswer } from './helpers'

test.describe('Адверсариальная честность (live)', () => {
  test('запрос вне корпуса → «не найдено» и 0 цитат', async ({ page }, info) => {
    test.skip(
      info.project.name === 'mock',
      'моки всегда возвращают пакет; честность проверяется на живом retrieval-гейтинге',
    )
    await page.goto('/')
    const q = 'выплавка алюминия Холла—Эру в Исландии'
    await page.getByPlaceholder(/скорость циркуляции католита/).fill(q)
    await page.getByRole('button', { name: /^Найти$/ }).click()
    await waitForAnswer(page)

    // 0 цитат: раздела «Источники» нет
    await expect(page.getByRole('heading', { name: 'Источники' })).toHaveCount(0)
    // ответ честно сообщает, что доказательств не найдено
    await expect(page.locator('.md').first()).toContainText(/не найден/i)
  })
})
