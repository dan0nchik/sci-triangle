import { test, expect } from '@playwright/test'

test.describe('Подписки', () => {
  test('создать подписку → появляется в списке', async ({ page }) => {
    await page.goto('/subscriptions')
    await expect(page.getByRole('heading', { name: 'Подписки и уведомления' })).toBeVisible()
    // на live список подписок грузится с сервера асинхронно (persist в sqlite) —
    // дождаться, пока начальная загрузка отрендерится, иначе re-render дёргает кнопку
    await page.waitForLoadState('networkidle')

    const query = `E2E подписка ${Date.now()}`
    const input = page.getByPlaceholder('Новый сохранённый запрос…')
    await input.fill(query)
    // Enter в поле = создать (стабильнее, чем клик по кнопке, которую двигает re-render)
    await input.press('Enter')

    // подписка появляется в списке слева
    await expect(page.getByText(query)).toBeVisible({ timeout: 20_000 })
  })
})
