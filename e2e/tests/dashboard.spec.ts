import { test, expect } from '@playwright/test'
import { shot } from './helpers'

test.describe('Дашборд руководителя', () => {
  test('счётчики и блоки рендерятся', async ({ page }, info) => {
    await page.goto('/dashboard')
    await expect(page.getByRole('heading', { name: 'Дашборд руководителя' })).toBeVisible()
    // KPI-счётчики
    await expect(page.getByText('Узлов графа')).toBeVisible({ timeout: 30_000 })
    await expect(page.getByText('Рёбер графа')).toBeVisible()
    await expect(page.getByText('Утверждений (Assertion)')).toBeVisible()
    // блок покрытия
    await expect(page.getByText('Обработано корпуса')).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Покрытие по доменам' })).toBeVisible()
    await shot(page, info, 'dashboard')
  })

  test('на live счётчик корпуса > 0', async ({ page }, info) => {
    test.skip(info.project.name === 'mock', 'счётчик корпуса из живого /api/stats')
    await page.goto('/dashboard')
    // «Обработано корпуса N из M» — N (n_documents) должно быть > 0
    // (светлая тема Норникеля: текст .text-fg, не .text-white)
    const processed = page.locator('div.text-2xl.font-semibold.text-fg').first()
    await expect(processed).toBeVisible({ timeout: 30_000 })
    const txt = (await processed.textContent()) ?? ''
    const n = Number(txt.replace(/[^\d]/g, '').slice(0, 6))
    // берём первое число (processed) — оно перед «из»
    const firstNum = Number((txt.match(/\d[\d\s]*/)?.[0] ?? '0').replace(/\s/g, ''))
    expect(firstNum).toBeGreaterThan(0)
    expect(n).toBeGreaterThan(0)
  })
})
