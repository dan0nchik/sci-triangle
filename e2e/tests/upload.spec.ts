import { test, expect } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import { shot } from './helpers'

// Маленький реальный PDF из корпуса — для live-прогона (дедуп по sha256:
// повторная загрузка возвращает cached=true и готовый результат мгновенно).
const LIVE_PDF = path.resolve(
  process.cwd(),
  '../data/Задача 2. Научный клубок/Источники информации/Доклады/Тяпкина ПА_Пермь_Зимняя школа.pdf',
)

test.describe('Загрузка документа (Upload-Pipeline)', () => {
  test('модал: файл → стадии pipeline → сводка + превью графа', async ({ page }, info) => {
    const isMock = info.project.name === 'mock'
    if (!isMock && !fs.existsSync(LIVE_PDF)) {
      test.skip(true, 'нет тестового PDF из корпуса для live-прогона')
    }

    await page.goto('/')

    // кнопка видима по умолчанию (без фича-флага)
    const openBtn = page.getByRole('button', { name: /Добавить документ/ })
    await expect(openBtn).toBeVisible()
    await openBtn.click()

    const modal = page.getByTestId('upload-modal')
    await expect(modal).toBeVisible()

    // подложить файл в скрытый input: mock — синтетический буфер (детерминированный
    // прогон стадий), live — реальный PDF из корпуса (cached → мгновенный done)
    if (isMock) {
      await modal.locator('input[type="file"]').setInputFiles({
        name: 'nickel_experiment.pdf',
        mimeType: 'application/pdf',
        buffer: Buffer.from('%PDF-1.4 test upload for sci-tangle demo'),
      })
    } else {
      await modal.locator('input[type="file"]').setInputFiles(LIVE_PDF)
    }
    await modal.getByRole('button', { name: 'Загрузить и обработать' }).click()

    // степпер стадий появился и стадии проходят
    await expect(modal.getByText('Извлечение текста')).toBeVisible({ timeout: 15_000 })
    await expect(modal.getByText('Индексация', { exact: true })).toBeVisible()
    await expect(modal.getByText('Фрагмент графа', { exact: true })).toBeVisible()
    // (эмбеддинги могут быть «отложено» — это нейтральный статус, не ошибка)
    await expect(modal.getByText(/готово/).first()).toBeVisible({ timeout: 60_000 })

    // финал: сводка n_chunks / n_entities / n_edges + превью фрагмента графа
    await expect(modal.getByText('чанков', { exact: true })).toBeVisible({ timeout: 60_000 })
    await expect(modal.getByText('сущностей', { exact: true })).toBeVisible()
    await expect(modal.getByText('связей в графе', { exact: true })).toBeVisible()
    await expect(modal.getByText(/Фрагмент графа документа/)).toBeVisible()
    await expect(modal.getByRole('button', { name: /Открыть в графе/ })).toBeVisible()

    await shot(page, info, 'upload-modal')

    // закрытие
    await modal.getByRole('button', { name: 'Готово' }).click()
    await expect(modal).not.toBeVisible()
  })
})
