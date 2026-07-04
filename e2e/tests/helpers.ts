import { type Page, type TestInfo, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

export const SCREENSHOTS_DIR = path.resolve(process.cwd(), 'screenshots')

export function ensureScreenshotsDir() {
  if (!fs.existsSync(SCREENSHOTS_DIR)) fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true })
}

export async function shot(page: Page, info: TestInfo, name: string) {
  ensureScreenshotsDir()
  const file = path.join(SCREENSHOTS_DIR, `${name}-${info.project.name}.png`)
  await page.screenshot({ path: file, fullPage: true })
  return file
}

/** Открыть страницу поиска и запустить первый golden-запрос кликом по примеру. */
export async function runGoldenSearch(page: Page, index = 1) {
  await page.goto('/')
  // кликабельные примеры — golden queries
  const examples = page.locator('button.chip', { hasText: /Циркуляция|Обессоливание|МПГ|шахтных/ })
  await expect(examples.first()).toBeVisible()
  await examples.nth(index).click()
  await waitForAnswer(page)
}

/** Дождаться, пока отрендерится evidence packet (markdown-ответ). */
export async function waitForAnswer(page: Page) {
  // метка интента появляется вместе с ответом
  await expect(page.getByText(/интент:/).first()).toBeVisible({ timeout: 75_000 })
  await expect(page.locator('.md').first()).toBeVisible({ timeout: 75_000 })
}

/** Сменить роль (демо-режим). Селектор перенесён в свёрнутое меню «Демо-режимы». */
export async function setRole(page: Page, label: string) {
  // Раскрыть меню «Демо-режимы (доп. возможность)», если оно свёрнуто.
  const summary = page.locator('aside details summary', { hasText: 'Демо-режимы' })
  if (await summary.count()) {
    const details = page.locator('aside details')
    const isOpen = await details
      .evaluate((el) => (el as HTMLDetailsElement).open)
      .catch(() => false)
    if (!isOpen) await summary.click()
  }
  const select = page.locator('aside details select')
  await select.selectOption({ label })
}
